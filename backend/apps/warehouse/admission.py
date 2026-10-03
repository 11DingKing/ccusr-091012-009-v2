"""
移交准入判定引擎

值班员接收外部单位送交的受控物资时，依据“单位身份 + 物资品类 + 接收日期”
选择适用的准入版本（授权或许可），输出通过/拒绝结论及具体判定依据。

优先级规则（固定，不允许值班员临场选择）：
1. 名称识别：填报名称命中单位“当前名称”或任一“历史名称记录”均视为同一单位；
   历史名称全局唯一，因此一个名称最多解析到一个单位。
2. 暂停/终止合作的单位不得发起新移交，即使其持有有效授权或紧急临时许可
   （合作状态优先级高于授权版本）；仅可凭已批准且未使用的退回批准单完成退回。
3. 准入版本选择：在接收日期处于有效期内、未撤销、且覆盖送交品类的版本中——
   a. 紧急临时许可优先于常规授权；
   b. 同类版本中有效期开始日期更晚（签发更新）的版本优先；
   c. 仍相同则截止日期更晚、编号更大者优先。
"""
from dataclasses import dataclass, field
from datetime import date

from django.db import transaction
from django.utils import timezone

from .models import (
    Authorization, Handover, ReturnApproval, TransferUnit, TransferUnitNameRecord,
)


@dataclass
class AdmissionDecision:
    """一次准入判定的结构化结论"""
    purpose: str
    on_date: date
    unit_name: str
    accepted: bool = False
    reason_code: str = ''
    reason_message: str = ''
    unit: TransferUnit = None
    name_match_type: str = ''          # current / alias
    matched_name_record: TransferUnitNameRecord = None
    authorization: Authorization = None
    eligible_authorizations: list = field(default_factory=list)
    return_approval: ReturnApproval = None
    basis: list = field(default_factory=list)

    @property
    def basis_text(self):
        return '\n'.join(f'{i + 1}. {line}' for i, line in enumerate(self.basis))


def _resolve_unit(unit_name):
    """按当前名称 → 历史名称的顺序解析移交单位身份"""
    unit = TransferUnit.objects.filter(name=unit_name).first()
    if unit:
        return unit, 'current', None
    record = TransferUnitNameRecord.objects.filter(name=unit_name).select_related('unit').first()
    if record:
        return record.unit, 'alias', record
    return None, '', None


def _select_authorization(unit, category, on_date):
    """在覆盖该品类、当日有效的版本中按固定优先级选出适用版本"""
    authorizations = list(
        unit.authorizations.prefetch_related('categories').all()
    )
    eligible, considered = [], []
    for auth in authorizations:
        if auth.is_revoked:
            considered.append((auth, False, f'版本已于{auth.revoked_at.date()}撤销，不参与判定'))
            continue
        in_date = auth.valid_from <= on_date <= auth.valid_to
        covered = auth.categories.filter(pk=category.pk).exists()
        if not in_date:
            considered.append((auth, False, f'有效期{auth.valid_from}~{auth.valid_to}不覆盖接收日期{on_date}'))
            continue
        if not covered:
            considered.append((auth, False, f'授权品类范围不包含“{category.name}”'))
            continue
        considered.append((auth, True, '当日有效且覆盖送交品类'))
        eligible.append(auth)

    if not eligible:
        return None, considered

    def rank(auth):
        return (
            0 if auth.kind == 'emergency' else 1,   # 紧急临时许可优先
            -(auth.valid_from.toordinal()),          # 开始日期更晚者优先
            -(auth.valid_to.toordinal()),
            -auth.pk,
        )

    selected = sorted(eligible, key=rank)[0]
    return selected, considered


def evaluate_admission(*, unit_name, category, on_date,
                       purpose='handover', return_document_no=None):
    """执行一次准入判定，不写库"""
    decision = AdmissionDecision(
        purpose=purpose, on_date=on_date, unit_name=unit_name
    )

    # 1. 身份识别
    unit, match_type, name_record = _resolve_unit((unit_name or '').strip())
    if unit is None:
        decision.reason_code = 'unit_not_found'
        decision.reason_message = '查无该移交单位：当前名称及历史名称均无登记，禁止接收'
        decision.basis.append(f'填报单位“{unit_name}”在移交单位名册（含曾用名）中无匹配')
        return decision

    decision.unit = unit
    decision.name_match_type = match_type
    decision.matched_name_record = name_record
    if match_type == 'current':
        decision.basis.append(f'填报名称“{unit.name}”为单位当前名称，身份直接确认')
    else:
        decision.basis.append(
            f'填报名称“{unit_name}”为单位“{unit.name}”的历史登记名称'
            f'（{name_record.effective_from}起登记），按同一单位身份处理'
        )
    decision.basis.append(f'单位当前合作状态：{unit.get_status_display()}')

    # 2. 退回业务：暂停单位唯一被允许的通道
    if purpose == 'return':
        doc_no = (return_document_no or '').strip()
        if not doc_no:
            decision.reason_code = 'return_approval_missing'
            decision.reason_message = '退回须提供已批准的退回批准单号'
            decision.basis.append('未提供退回批准单号，无法按退回通道接收')
            return decision

        return_approval = ReturnApproval.objects.filter(unit=unit, document_no=doc_no).first()
        if return_approval is None:
            decision.reason_code = 'return_approval_missing'
            decision.reason_message = f'退回批准单“{doc_no}”不存在或不属于该单位'
            decision.basis.append(f'单位名下查无退回批准单“{doc_no}”')
            return decision
        if not return_approval.is_usable:
            decision.reason_code = 'return_approval_unavailable'
            decision.reason_message = f'退回批准单状态为“{return_approval.get_status_display()}”，不能再用于接收'
            decision.basis.append(f'退回批准单“{doc_no}”状态：{return_approval.get_status_display()}')
            return decision
        if not return_approval.matches_category(category):
            decision.reason_code = 'return_approval_mismatch'
            decision.reason_message = '退回批准单登记品类与本次送交品类不一致'
            decision.basis.append(
                f'退回批准单限定品类“{return_approval.category.name}”，'
                f'本次送交品类为“{category.name}”'
            )
            return decision

        decision.return_approval = return_approval
        decision.accepted = True
        decision.reason_code = 'ok'
        decision.reason_message = '接收通过：退回通道'
        if unit.is_suspended:
            decision.basis.append(
                f'单位已暂停合作，仅允许完成已批准退回；退回批准单“{doc_no}”'
                f'已批准且品类相符，准予退回接收'
            )
        else:
            decision.basis.append(f'退回批准单“{doc_no}”已批准且品类相符，准予退回接收')
        return decision

    # 3. 新移交：合作状态优先于一切授权
    if unit.is_suspended:
        decision.reason_code = 'unit_suspended'
        decision.reason_message = '该单位已暂停（终止）合作，不能发起新移交，仅可完成已批准的退回'
        decision.basis.append(
            '合作状态为“%s”，新移交一律拒绝；即使存在有效授权或紧急临时许可也不接收'
            % unit.get_status_display()
        )
        return decision

    # 4. 选择适用准入版本
    selected, considered = _select_authorization(unit, category, on_date)
    for auth, usable, note in considered:
        prefix = '✓' if usable else '✗'
        decision.basis.append(
            f'{prefix} {auth.get_kind_display()}'
            f'（{auth.valid_from}~{auth.valid_to}，文号{auth.document_no or "无"}）：{note}'
        )

    if selected is None:
        decision.reason_code = 'not_authorized'
        decision.reason_message = (
            f'该单位在{on_date}没有覆盖“{category.name}”的有效准入版本，禁止接收入账'
        )
        decision.basis.append(f'接收日期{on_date}、品类“{category.name}”无任一适用版本，结论为拒绝')
        return decision

    decision.authorization = selected
    decision.eligible_authorizations = [a for a, ok, _ in considered if ok]
    if len(decision.eligible_authorizations) > 1:
        decision.basis.append(
            '存在%d个授权重叠的适用版本，按优先级裁定：紧急临时许可优先于常规授权，'
            '同类以有效期开始日期更晚（签发更新）者优先' % len(decision.eligible_authorizations)
        )
    decision.basis.append(
        f'适用准入版本：{selected.get_kind_display()}（{selected.valid_from}~'
        f'{selected.valid_to}，文号{selected.document_no or "无"}），接收通过'
    )
    decision.accepted = True
    decision.reason_code = 'ok'
    decision.reason_message = '接收通过'
    return decision


def record_handover(*, decision, category, variety=None, material_name='', material_code='',
                    quantity=0, batch_no='', operator=None):
    """将判定结论登记入正式台账；退回同时核销退回批准单"""
    with transaction.atomic():
        handover = Handover.objects.create(
            unit=decision.unit,
            unit_name_snapshot=decision.unit_name,
            category=category,
            variety=variety,
            material_name=material_name,
            material_code=material_code,
            quantity=quantity,
            batch_no=batch_no,
            purpose=decision.purpose,
            decision='accepted' if decision.accepted else 'rejected',
            handover_date=decision.on_date,
            authorization=decision.authorization,
            return_approval=decision.return_approval,
            basis=decision.basis_text,
            reject_reason='' if decision.accepted else decision.reason_message,
            received_by=operator,
        )
        if decision.accepted and decision.purpose == 'return' and decision.return_approval:
            return_approval = decision.return_approval
            return_approval.status = 'used'
            return_approval.used_handover = handover
            return_approval.used_at = timezone.now()
            return_approval.save(update_fields=['status', 'used_handover', 'used_at'])
    return handover
