"""
移交单位与准入管理模型

值班员接收外部单位送交的受控物资时，不再只凭单位名称登记，而是依据
"准入版本"判定：按物资类型（品类）与收件日期选取适用的授权记录，
并结合单位合作状态、名称变更链与紧急临时许可给出可追溯的通过/拒绝结论。

优先级（高 -> 低）：
1. 单位暂停状态（全局闸门，仅放行已批准的退回）
2. 紧急临时许可（仅在其有效窗口内覆盖常规授权）
3. 常规准入授权（按品类与生效日期选择版本）
4. 单位名称变更链（仅用于把旧名称解析到当前主体）
"""
from django.db import models
from django.utils import timezone

from apps.authentication.models import User
from .models import Category, Goods


class TransferUnit(models.Model):
    """移交单位（外部送交受控物资的单位）"""

    STATUS_ACTIVE = 'active'
    STATUS_SUSPENDED = 'suspended'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, '正常合作'),
        (STATUS_SUSPENDED, '暂停合作'),
    ]

    name = models.CharField('单位名称', max_length=100, unique=True)
    status = models.CharField(
        '合作状态', max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE
    )
    suspended_at = models.DateTimeField('暂停时间', null=True, blank=True)
    suspend_reason = models.CharField('暂停原因', max_length=200, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_transfer_units', verbose_name='创建人'
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_transfer_unit'
        verbose_name = '移交单位'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    @property
    def is_suspended(self):
        return self.status == self.STATUS_SUSPENDED

    def suspend(self, reason='', at=None):
        """暂停合作：冻结新移交入口，但不影响已批准退回的执行"""
        self.status = self.STATUS_SUSPENDED
        self.suspended_at = at or timezone.now()
        self.suspend_reason = reason
        self.save(update_fields=['status', 'suspended_at', 'suspend_reason', 'updated_at'])

    def resume(self):
        """恢复合作"""
        self.status = self.STATUS_ACTIVE
        self.suspended_at = None
        self.suspend_reason = ''
        self.save(update_fields=['status', 'suspended_at', 'suspend_reason', 'updated_at'])

    def resolve(self, name, at=None):
        """按名称（含历史名称）解析单位主体。

        名称变更不改变单位身份：当前名称与任一曾用名均指向本单位。
        返回 (unit, matched_alias)，无法解析时返回 (None, False)。
        """
        at = at or timezone.now()
        normalized = (name or '').strip()
        if not normalized:
            return None, False
        if self.name == normalized:
            return self, False
        changed = self.name_changes.filter(
            models.Q(previous_name=normalized)
            & (models.Q(effective_from__lte=at) | models.Q(effective_from__isnull=True))
        ).order_by('-effective_from').first()
        if changed:
            return self, True
        return None, False


class UnitNameChange(models.Model):
    """单位名称变更记录（曾用名 -> 现名）"""

    unit = models.ForeignKey(
        TransferUnit, on_delete=models.CASCADE,
        related_name='name_changes', verbose_name='移交单位'
    )
    previous_name = models.CharField('曾用名', max_length=100)
    current_name = models.CharField('变更后名称', max_length=100)
    effective_from = models.DateTimeField('生效时间', default=timezone.now)
    reason = models.CharField('变更原因', max_length=200, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='unit_name_changes', verbose_name='登记人'
    )
    created_at = models.DateTimeField('登记时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_unit_name_change'
        verbose_name = '单位名称变更'
        verbose_name_plural = verbose_name
        ordering = ['-effective_from', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['unit', 'previous_name'],
                name='uniq_unit_previous_name',
            ),
        ]

    def __str__(self):
        return f"{self.previous_name} -> {self.current_name}"

    @property
    def is_effective(self):
        return self.effective_from is None or self.effective_from <= timezone.now()


class AccessGrant(models.Model):
    """准入授权（按物资类型授予的准入版本）

    同一单位、同一品类可存在多个版本（授权范围调整后新增版本），
    收件时取生效日期不晚于收件日期的最新版本；版本有效期由
    effective_from / effective_to 共同界定。
    """

    SCOPE_ALL = 'all'
    SCOPE_SPECIFIED = 'specified'
    SCOPE_CHOICES = [
        (SCOPE_ALL, '全部品类'),
        (SCOPE_SPECIFIED, '指定品类'),
    ]

    unit = models.ForeignKey(
        TransferUnit, on_delete=models.CASCADE,
        related_name='grants', verbose_name='移交单位'
    )
    scope_type = models.CharField(
        '授权范围', max_length=20, choices=SCOPE_CHOICES, default=SCOPE_SPECIFIED
    )
    categories = models.ManyToManyField(
        Category, blank=True, related_name='access_grants', verbose_name='授权品类'
    )
    effective_from = models.DateTimeField('生效日期', null=True, blank=True)
    effective_to = models.DateTimeField('失效日期', null=True, blank=True)
    version_no = models.CharField('授权文号/版本', max_length=50, blank=True)
    remark = models.CharField('备注', max_length=200, blank=True)
    is_active = models.BooleanField('是否启用', default=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_access_grants', verbose_name='登记人'
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_access_grant'
        verbose_name = '准入授权'
        verbose_name_plural = verbose_name
        ordering = ['-effective_from', '-created_at']

    def __str__(self):
        return f"{self.unit} - {self.get_scope_type_display()} - {self.version_no or self.pk}"

    def in_effect(self, at=None):
        """指定日期是否处于本版本有效期内"""
        at = at or timezone.now()
        if not self.is_active:
            return False
        if self.effective_from and at < self.effective_from:
            return False
        if self.effective_to and at > self.effective_to:
            return False
        return True

    def covers_category(self, category):
        """授权范围是否覆盖给定品类"""
        if self.scope_type == self.SCOPE_ALL:
            return True
        if category is None:
            return False
        return self.categories.filter(pk=category.pk).exists()


class EmergencyPermit(models.Model):
    """紧急临时许可（优先级最高的一次性/短期准入）

    仅在 valid_from ~ valid_to 窗口内有效，可限定物资类型，
    可指定批次用途；用于单位授权暂停、过期或范围不符时的紧急收件。
    """

    unit = models.ForeignKey(
        TransferUnit, on_delete=models.CASCADE,
        related_name='emergency_permits', verbose_name='移交单位'
    )
    reason = models.CharField('紧急事由', max_length=200)
    scope_type = models.CharField(
        '许可范围', max_length=20, choices=AccessGrant.SCOPE_CHOICES,
        default=AccessGrant.SCOPE_SPECIFIED
    )
    categories = models.ManyToManyField(
        Category, blank=True, related_name='emergency_permits', verbose_name='许可品类'
    )
    valid_from = models.DateTimeField('有效期开始')
    valid_to = models.DateTimeField('有效期截止')
    approved_by = models.CharField('批准人', max_length=50)
    used_count = models.PositiveIntegerField('已使用次数', default=0)
    max_uses = models.PositiveIntegerField('最大使用次数', null=True, blank=True)
    is_revoked = models.BooleanField('是否已撤销', default=False)
    remark = models.CharField('备注', max_length=200, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_emergency_permits', verbose_name='登记人'
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_emergency_permit'
        verbose_name = '紧急临时许可'
        verbose_name_plural = verbose_name
        ordering = ['-valid_from', '-created_at']

    def __str__(self):
        return f"{self.unit} - 紧急许可({self.valid_from.date()}~{self.valid_to.date()})"

    def in_effect(self, at=None):
        at = at or timezone.now()
        if self.is_revoked:
            return False
        if not (self.valid_from <= at <= self.valid_to):
            return False
        if self.max_uses is not None and self.used_count >= self.max_uses:
            return False
        return True

    def covers_category(self, category):
        if self.scope_type == AccessGrant.SCOPE_ALL:
            return True
        if category is None:
            return False
        return self.categories.filter(pk=category.pk).exists()


class ReturnApproval(models.Model):
    """退回来件批准（外部单位退回物资的预先批准）

    单位被暂停合作后，新移交一律拒绝，仅允许持有效批准文号完成退回；
    值班员收件时按 单位 + 物资 + 文号 + 剩余数量 + 有效期 核验。
    goods 为空表示单位级批准（适用于该单位任一批退回物资）。
    """

    unit = models.ForeignKey(
        TransferUnit, on_delete=models.CASCADE,
        related_name='return_approvals', verbose_name='退回单位'
    )
    approval_no = models.CharField('批准文号', max_length=50, unique=True)
    goods = models.ForeignKey(
        Goods, on_delete=models.PROTECT, null=True, blank=True,
        related_name='return_approvals', verbose_name='批准退回货物'
    )
    approved_quantity = models.DecimalField('批准数量', max_digits=12, decimal_places=2)
    used_quantity = models.DecimalField('已完成数量', max_digits=12, decimal_places=2, default=0)
    valid_from = models.DateTimeField('有效期开始', null=True, blank=True)
    valid_to = models.DateTimeField('有效期截止', null=True, blank=True)
    is_revoked = models.BooleanField('是否已撤销', default=False)
    remark = models.CharField('备注', max_length=200, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_return_approvals', verbose_name='登记人'
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_return_approval'
        verbose_name = '退回来件批准'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.approval_no} - {self.unit}"

    @property
    def remaining_quantity(self):
        return self.approved_quantity - self.used_quantity

    def in_effect(self, at=None):
        at = at or timezone.now()
        if self.is_revoked:
            return False
        if self.valid_from and at < self.valid_from:
            return False
        if self.valid_to and at > self.valid_to:
            return False
        return True

    def matches(self, unit, goods, quantity, at=None):
        """是否与本次退回匹配且有足额剩余"""
        if self.unit_id != unit.id or not self.in_effect(at):
            return False
        if self.goods_id is not None and self.goods_id != goods.id:
            return False
        return self.remaining_quantity >= quantity


class CustodyTransfer(models.Model):
    """受控物资移交（送交）/退回记录

    每件物资的接收结论（accepted/decision）都带有 decision_basis，
    说明本次通过或拒绝所依据的准入版本、有效期与优先级规则。
    """

    KIND_HANDOVER = 'handover'
    KIND_RETURN = 'return'
    KIND_CHOICES = [
        (KIND_HANDOVER, '新移交'),
        (KIND_RETURN, '退回'),
    ]

    DECISION_ACCEPTED = 'accepted'
    DECISION_REJECTED = 'rejected'
    DECISION_CHOICES = [
        (DECISION_ACCEPTED, '接收通过'),
        (DECISION_REJECTED, '接收拒绝'),
    ]

    BASIS_UNIT = 'unit'
    BASIS_GRANT = 'grant'
    BASIS_EMERGENCY = 'emergency'
    BASIS_RETURN_APPROVAL = 'return_approval'
    BASIS_CHOICES = [
        (BASIS_UNIT, '单位状态'),
        (BASIS_GRANT, '常规授权'),
        (BASIS_EMERGENCY, '紧急临时许可'),
        (BASIS_RETURN_APPROVAL, '已批准退回'),
    ]

    kind = models.CharField('业务类型', max_length=20, choices=KIND_CHOICES, default=KIND_HANDOVER)
    goods = models.ForeignKey(
        Goods, on_delete=models.PROTECT,
        related_name='custody_transfers', verbose_name='货物'
    )
    unit = models.ForeignKey(
        TransferUnit, on_delete=models.PROTECT, null=True,
        related_name='transfers', verbose_name='移交单位'
    )
    unit_name_used = models.CharField('收件时使用的单位名称', max_length=100, blank=True)
    quantity = models.DecimalField('数量', max_digits=12, decimal_places=2)
    received_at = models.DateTimeField('收件时间', default=timezone.now)
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='custody_transfer_ops', verbose_name='值班员'
    )
    decision = models.CharField('接收结论', max_length=20, choices=DECISION_CHOICES)
    basis_type = models.CharField('依据类型', max_length=20, choices=BASIS_CHOICES, blank=True)
    grant = models.ForeignKey(
        AccessGrant, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='transfers', verbose_name='适用授权版本'
    )
    permit = models.ForeignKey(
        EmergencyPermit, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='transfers', verbose_name='适用紧急许可'
    )
    decision_basis = models.TextField('接收判定依据', blank=True)
    rejection_reason = models.CharField('拒绝原因', max_length=200, blank=True)
    return_approval_no = models.CharField('退回来件批准文号', max_length=50, blank=True)
    batch_no = models.CharField('批次号', max_length=50, blank=True)
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('登记时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_custody_transfer'
        verbose_name = '物资移交记录'
        verbose_name_plural = verbose_name
        ordering = ['-received_at', '-created_at']

    def __str__(self):
        return f"{self.get_kind_display()} - {self.unit} - {self.goods.name} - {self.get_decision_display()}"
