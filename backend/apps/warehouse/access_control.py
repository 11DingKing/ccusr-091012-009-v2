"""
收件准入判定服务

对外入口：evaluate_admission(...)
返回 AdmissionDecision，其中 basis 以结构化方式说明一次接收通过或拒绝的
具体依据（适用版本、有效期、名称解析、优先级裁决）。

优先级（高 -> 低）：
  P0 暂停闸门：单位暂停合作时，仅"已批准退回"可通过，新移交一律拒绝。
  P1 紧急临时许可：有效期窗口内，覆盖常规授权（范围不符/过期时的补救）。
  P2 常规准入授权：按物资品类 + 收件日期选取适用的最新生效版本。
  P3 名称变更链：只负责把曾用名解析到当前单位，本身不产生授权。
"""
from dataclasses import dataclass, field
from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    AccessGrant, CustodyTransfer, EmergencyPermit, ReturnApproval,
    TransferUnit, UnitNameChange,
)


@dataclass
class AdmissionBasis:
    """单次接收判定依据（用于查询结果与台账留痕）"""
    rule: str                       # 命中的优先级规则编号，如 P2
    rule_name: str                  # 规则名称
    detail: str                     # 人类可读的完整说明
    grant_id: int = None
    grant_version: str = ''
    grant_effective_from: datetime = None
    grant_effective_to: datetime = None
    permit_id: int = None
    return_approval_id: int = None
    unit_resolved_via_alias: bool = False   # 是否经由曾用名解析
    previous_name: str = ''

    def as_dict(self):
        fmt = lambda d: d.strftime('%Y-%m-%d %H:%M') if d else None
        return {
            'rule': self.rule,
            'rule_name': self.rule_name,
            'detail': self.detail,
            'grant_id': self.grant_id,
            'grant_version': self.grant_version,
            'grant_effective_from': fmt(self.grant_effective_from),
            'grant_effective_to': fmt(self.grant_effective_to),
            'permit_id': self.permit_id,
            'return_approval_id': self.return_approval_id,
            'unit_resolved_via_alias': self.unit_resolved_via_alias,
            'previous_name': self.previous_name,
        }


@dataclass
class AdmissionDecision:
    accepted: bool
    kind: str                       # handover / return
    unit: TransferUnit
    goods: object
    quantity: object
    received_at: datetime
    basis: AdmissionBasis = None
    rejection_reason: str = ''
    matched_grants: list = field(default_factory=list)   # 参与裁决的候选版本

    @property
    def summary(self):
        verdict = '接收通过' if self.accepted else '接收拒绝'
        return f"{verdict}：{self.basis.detail}" if self.basis else verdict


def _parse_at(at):
    """归一化收件时间：API 入参经 DRF 解析为 datetime；直接调用支持 date。"""
    import datetime as _dt

    if at is None:
        return timezone.now()
    if isinstance(at, _dt.date) and not isinstance(at, _dt.datetime):
        at = _dt.datetime.combine(at, _dt.time(23, 59, 59))
    if timezone.is_naive(at):
        return timezone.make_aware(at)
    return at


def resolve_unit(unit_name, at=None):
    """按名称解析移交单位主体（当前名称优先，其次曾用名变更链）。

    返回 (unit, previous_name)；无法解析时返回 (None, '')。
    """
    at = at or timezone.now()
    name = (unit_name or '').strip()
    if not name:
        return None, ''

    unit = TransferUnit.objects.filter(name=name).first()
    if unit:
        return unit, ''

    change = (
        UnitNameChange.objects.select_related('unit')
        .filter(previous_name=name)
        .filter(Q(effective_from__lte=at) | Q(effective_from__isnull=True))
        .order_by('-effective_from')
        .first()
    )
    if change:
        return change.unit, change.previous_name
    return None, ''


def select_grant(unit, category, at):
    """按品类与日期选取适用的常规授权版本。

    规则：生效日期 <= 收件日期（或为空）且未失效（effective_to >= 收件日期
    或为空）的启用版本中，范围覆盖该品类、生效日期最新者为准入版本。
    返回 (grant, candidates_in_scope)，candidates 用于解释范围不符。
    """
    grants = list(
        unit.grants.filter(is_active=True)
        .prefetch_related('categories')
        .order_by('-effective_from', '-created_at')
    )
    in_window = [g for g in grants if g.in_effect(at)]
    covering = [g for g in in_window if g.covers_category(category)]
    return (covering[0] if covering else None), in_window


def select_permit(unit, category, at):
    """选取当前有效的紧急临时许可（窗口内、未撤销、未超次数、范围覆盖）"""
    permits = [
        p for p in unit.emergency_permits.all()
        if p.in_effect(at) and p.covers_category(category)
    ]
    permits.sort(key=lambda p: p.valid_to)
    return permits[0] if permits else None


def _grant_label(grant):
    window = _format_window(grant.effective_from, grant.effective_to)
    scope = grant.get_scope_type_display()
    if grant.scope_type == AccessGrant.SCOPE_SPECIFIED:
        names = '、'.join(grant.categories.values_list('name', flat=True)) or '未指定品类'
        scope = f'指定品类（{names}）'
    version = f"，文号/版本「{grant.version_no}」" if grant.version_no else ''
    return f"授权#{grant.pk}{version}，范围：{scope}，有效期：{window}"


def _permit_label(permit):
    window = _format_window(permit.valid_from, permit.valid_to)
    scope = permit.get_scope_type_display()
    if permit.scope_type == AccessGrant.SCOPE_SPECIFIED:
        names = '、'.join(permit.categories.values_list('name', flat=True)) or '未指定品类'
        scope = f'指定品类（{names}）'
    return (
        f"紧急临时许可#{permit.pk}（事由：{permit.reason}，批准人：{permit.approved_by}），"
        f"范围：{scope}，有效期：{window}"
    )


def _format_window(start, end):
    fmt = lambda d: d.strftime('%Y-%m-%d %H:%M') if d else '长期'
    left = fmt(start)
    right = fmt(end)
    if start is None and end is None:
        return '长期有效'
    return f'{left} 至 {right}'


def evaluate_admission(*, unit_name, goods, quantity, kind, at=None,
                       return_approval_no='', batch_no=''):
    """执行一次收件准入判定（不落库）。

    参数:
      unit_name: 值班员填写/选择的单位名称（可能为曾用名）
      goods:     Goods 实例，物资类型取 goods.variety.category
      quantity:  本次数量
      kind:      'handover' 新移交 / 'return' 退回
      at:        收件日期/时间（默认当前）
      return_approval_no: 退回来件批准文号（退回时必填）
    返回 AdmissionDecision。
    """
    at = _parse_at(at)
    category = getattr(getattr(goods, 'variety', None), 'category', None)

    unit, previous_name = resolve_unit(unit_name, at=at)
    alias_note = ''
    if previous_name:
        alias_note = (
            f"来件名称「{previous_name}」经名称变更链解析为当前单位"
            f"「{unit.name}」（P3 名称变更仅用于主体识别，不单独产生授权）；"
        )

    if unit is None:
        basis = AdmissionBasis(
            rule='P3', rule_name='单位名称解析',
            detail=f'未找到名称为「{unit_name}」的移交单位，也无匹配的曾用名变更记录，无法建立准入依据。',
        )
        return AdmissionDecision(False, kind, None, goods, quantity, at,
                                 basis=basis, rejection_reason='移交单位不存在')

    def make_decision(accepted, basis, reason=''):
        if previous_name:
            basis.unit_resolved_via_alias = True
            basis.previous_name = previous_name
        return AdmissionDecision(accepted, kind, unit, goods, quantity, at,
                                 basis=basis, rejection_reason=reason)

    # ---------- 退回：一律凭"退回来件批准"核验，与单位合作状态无关 ----------
    # （暂停单位被冻结的只是新移交入口，已批准退回始终放行；
    #   正常单位的退回同样需要批准文号，避免无凭证退回进入台账。）
    if kind == CustodyTransfer.KIND_RETURN:
        approval = _find_return_approval(unit, goods, quantity, return_approval_no, at)
        if approval:
            state_note = (
                f"单位处于暂停合作状态（{_suspend_text(unit)}），新移交已冻结；"
                if unit.is_suspended else
                "单位为正常合作状态；"
            )
            basis = AdmissionBasis(
                rule='P0', rule_name='已批准退回',
                detail=(
                    f"{state_note}本次为退回业务，持有效批准文号"
                    f"「{approval.approval_no}」，批准数量{approval.approved_quantity}，"
                    f"剩余可退{approval.remaining_quantity}，有效期："
                    f"{_format_window(approval.valid_from, approval.valid_to)}，准予完成退回。"
                ),
                return_approval_id=approval.pk,
            )
            if alias_note:
                basis.detail = alias_note + basis.detail
            return make_decision(True, basis)
        reason = _return_approval_failure(unit, goods, quantity, return_approval_no, at)
        suspended_note = (
            '单位处于暂停合作状态，仅允许持有效批准文号完成退回；'
            if unit.is_suspended else ''
        )
        basis = AdmissionBasis(
            rule='P0', rule_name='退回批准核验',
            detail=f"{suspended_note}{reason}",
        )
        if alias_note:
            basis.detail = alias_note + basis.detail
        return make_decision(False, basis, reason)

    # ---------- P0 暂停闸门（仅作用于新移交） ----------
    if unit.is_suspended:
        # 暂停单位发起新移交：即使有紧急许可也不允许（暂停为最高优先级全局闸门）
        permit_during_suspension = select_permit(unit, category, at)
        extra = ''
        if permit_during_suspension:
            extra = (
                f"虽存在{_permit_label(permit_during_suspension)}，"
                f"但暂停状态（P0）优先级高于紧急临时许可（P1），不得发起新移交。"
            )
        basis = AdmissionBasis(
            rule='P0', rule_name='暂停闸门',
            detail=(
                f"单位「{unit.name}」已暂停合作（{_suspend_text(unit)}），"
                f"只能完成已批准的退回，不能发起新移交。{extra}"
            ),
            permit_id=permit_during_suspension.pk if permit_during_suspension else None,
        )
        if alias_note:
            basis.detail = alias_note + basis.detail
        return make_decision(False, basis, '单位已暂停合作，不能发起新移交')

    # ---------- 正常合作单位的新移交 ----------
    grant, in_window_grants = select_grant(unit, category, at)
    permit = select_permit(unit, category, at)

    # P1 紧急临时许可：窗口内优先于常规授权
    if permit:
        basis = AdmissionBasis(
            rule='P1', rule_name='紧急临时许可',
            detail=(
                f"{alias_note}按物资类型「{category.name if category else '未分类'}」与收件日期"
                f"{at.strftime('%Y-%m-%d %H:%M')}选取准入依据：{_permit_label(permit)}。"
                f"紧急临时许可（P1）在有效期内优先于常规授权（P2），准予接收。"
            ),
            permit_id=permit.pk,
            grant_id=grant.pk if grant else None,
            grant_version=grant.version_no if grant else '',
        )
        return make_decision(True, basis)

    # P2 常规授权
    if grant:
        basis = AdmissionBasis(
            rule='P2', rule_name='常规准入授权',
            detail=(
                f"{alias_note}按物资类型「{category.name if category else '未分类'}」与收件日期"
                f"{at.strftime('%Y-%m-%d %H:%M')}选取准入版本：{_grant_label(grant)}。"
                f"该版本在有效期内且授权范围覆盖本品类，准予接收。"
            ),
            grant_id=grant.pk,
            grant_version=grant.version_no,
            grant_effective_from=grant.effective_from,
            grant_effective_to=grant.effective_to,
        )
        return make_decision(True, basis)

    # 拒绝：区分 无任何授权 / 有版本但过期 / 范围不符
    reason, detail = _explain_grant_miss(unit, category, at)
    basis = AdmissionBasis(
        rule='P2', rule_name='常规准入授权',
        detail=alias_note + detail,
    )
    return make_decision(False, basis, reason)


def _suspend_text(unit):
    when = unit.suspended_at.strftime('%Y-%m-%d %H:%M') if unit.suspended_at else '时间未记录'
    why = f"，原因：{unit.suspend_reason}" if unit.suspend_reason else ''
    return f'自{when}起暂停{why}'


def _find_return_approval(unit, goods, quantity, approval_no, at):
    if not approval_no:
        return None
    approval = (
        ReturnApproval.objects
        .filter(approval_no=approval_no.strip(), unit=unit)
        .first()
    )
    if approval and approval.matches(unit, goods, quantity, at):
        return approval
    return None


def _return_approval_failure(unit, goods, quantity, approval_no, at):
    if not approval_no:
        return '本次退回未提供批准文号，无法核验，予以拒绝。'
    approval = ReturnApproval.objects.filter(
        approval_no=approval_no.strip(), unit=unit
    ).first()
    if not approval:
        return f'批准文号「{approval_no}」不存在或不属于该单位，予以拒绝。'
    if approval.is_revoked:
        return f'批准文号「{approval_no}」已被撤销，予以拒绝。'
    if not approval.in_effect(at):
        return (
            f'批准文号「{approval_no}」不在有效期内（'
            f'{_format_window(approval.valid_from, approval.valid_to)}），予以拒绝。'
        )
    if approval.goods_id is not None and approval.goods_id != goods.id:
        return f'批准文号「{approval_no}」核准的物资与本次来件不符，予以拒绝。'
    if approval.remaining_quantity < quantity:
        return (
            f'批准文号「{approval_no}」剩余可退数量{approval.remaining_quantity}'
            f'小于本次数量{quantity}，予以拒绝。'
        )
    return '批准文号核验未通过，予以拒绝。'


def _explain_grant_miss(unit, category, at):
    """无适用常规授权时，区分过期、未生效、范围不符三种具体依据"""
    all_grants = list(unit.grants.filter(is_active=True).prefetch_related('categories'))
    cat_name = category.name if category else '未分类'

    if not all_grants:
        return (
            '单位无准入授权',
            f'单位「{unit.name}」未登记任何准入授权版本，物资类型「{cat_name}」不在准入范围内，拒绝接收。'
        )

    # 有效期窗口外
    not_started = [g for g in all_grants if g.effective_from and at < g.effective_from]
    expired = [g for g in all_grants if g.effective_to and at > g.effective_to]
    in_window = [g for g in all_grants if g.in_effect(at)]

    if not in_window:
        if expired and not not_started:
            latest = max(expired, key=lambda g: g.effective_to)
            return (
                '授权已过期',
                f'单位「{unit.name}」的最新授权版本（{_grant_label(latest)}）'
                f'已于{latest.effective_to.strftime("%Y-%m-%d %H:%M")}失效，'
                f'收件日期{at.strftime("%Y-%m-%d %H:%M")}无有效授权，拒绝接收。'
            )
        if not_started:
            nxt = min(not_started, key=lambda g: g.effective_from)
            return (
                '授权尚未生效',
                f'单位「{unit.name}」的授权（{_grant_label(nxt)}）'
                f'自{nxt.effective_from.strftime("%Y-%m-%d %H:%M")}起生效，'
                f'收件日期早于生效日期，拒绝接收。'
            )

    # 窗口内有版本但范围不覆盖
    if in_window:
        labels = '；'.join(_grant_label(g) for g in in_window)
        return (
            '授权范围不符',
            f'单位「{unit.name}」在收件日期有效授权版本为：{labels}；'
            f'其授权范围均不覆盖物资类型「{cat_name}」，拒绝接收。'
        )

    return ('无适用授权', f'单位「{unit.name}」的授权均不适用于收件日期与物资类型「{cat_name}」，拒绝接收。')


@transaction.atomic
def receive_transfer(*, unit_name, goods, quantity, kind, operator, at=None,
                     return_approval_no='', batch_no='', remark=''):
    """执行收件：先判定，通过则登记正式台账并扣减批准剩余额度。"""
    at = _parse_at(at)
    decision = evaluate_admission(
        unit_name=unit_name, goods=goods, quantity=quantity, kind=kind,
        at=at, return_approval_no=return_approval_no, batch_no=batch_no,
    )

    record = CustodyTransfer(
        kind=kind,
        goods=goods,
        unit=decision.unit,
        unit_name_used=unit_name,
        quantity=quantity,
        received_at=at,
        operator=operator,
        decision=(
            CustodyTransfer.DECISION_ACCEPTED if decision.accepted
            else CustodyTransfer.DECISION_REJECTED
        ),
        basis_type=_basis_type_for(decision),
        grant_id=decision.basis.grant_id,
        permit_id=decision.basis.permit_id,
        decision_basis=decision.basis.detail if decision.basis else '',
        rejection_reason=decision.rejection_reason,
        return_approval_no=return_approval_no,
        batch_no=batch_no,
        remark=remark,
    )
    record.save()

    if decision.accepted:
        if kind == CustodyTransfer.KIND_RETURN:
            approval = ReturnApproval.objects.get(pk=decision.basis.return_approval_id)
            approval.used_quantity += quantity
            approval.save(update_fields=['used_quantity'])
            record.return_approval_no = approval.approval_no
            record.save(update_fields=['return_approval_no'])
        elif decision.basis.permit_id:
            permit = EmergencyPermit.objects.get(pk=decision.basis.permit_id)
            permit.used_count += 1
            permit.save(update_fields=['used_count'])

    return decision, record


def _basis_type_for(decision):
    b = decision.basis
    if not b:
        return ''
    return {
        'P0': (
            CustodyTransfer.BASIS_RETURN_APPROVAL
            if decision.kind == CustodyTransfer.KIND_RETURN
            else CustodyTransfer.BASIS_UNIT
        ),
        'P1': CustodyTransfer.BASIS_EMERGENCY,
        'P2': CustodyTransfer.BASIS_GRANT,
        'P3': CustodyTransfer.BASIS_UNIT,
    }.get(b.rule, '')
