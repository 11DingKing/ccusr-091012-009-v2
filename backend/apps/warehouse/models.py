"""
库房管理模型
"""
from django.db import models
from django.utils import timezone
from apps.authentication.models import User


class Unit(models.Model):
    """单位模型"""
    name = models.CharField('单位名称', max_length=5, unique=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_units', verbose_name='创建人'
    )
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_unit'
        verbose_name = '单位'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    @property
    def is_linked(self):
        """是否已关联至品类"""
        return self.categories.exists()


class Category(models.Model):
    """品类模型"""
    name = models.CharField('品类名称', max_length=10, unique=True)
    unit = models.ForeignKey(
        Unit, on_delete=models.PROTECT,
        related_name='categories', verbose_name='单位'
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_categories', verbose_name='创建人'
    )
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_category'
        verbose_name = '品类'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    @property
    def is_linked(self):
        """是否已关联至品种"""
        return self.varieties.exists()


class Variety(models.Model):
    """品种模型"""
    name = models.CharField('品种名称', max_length=20)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT,
        related_name='varieties', verbose_name='所属品类'
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_varieties', verbose_name='创建人'
    )
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_variety'
        verbose_name = '品种'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        unique_together = ['category', 'name']
    
    def __str__(self):
        return f"{self.category.name} - {self.name}"
    
    @property
    def is_in_stock(self):
        """是否已入库"""
        return self.goods.exists()
    
    @property
    def unit_name(self):
        """获取单位名称"""
        return self.category.unit.name if self.category and self.category.unit else ''


class Goods(models.Model):
    """货物模型"""
    variety = models.ForeignKey(
        Variety, on_delete=models.CASCADE,
        related_name='goods', verbose_name='所属品种'
    )
    name = models.CharField('货物名称', max_length=200)
    code = models.CharField('货物编码', max_length=50, unique=True)
    specification = models.CharField('规格型号', max_length=200, blank=True)
    quantity = models.DecimalField('库存数量', max_digits=12, decimal_places=2, default=0)
    warning_threshold = models.DecimalField('预警阈值', max_digits=12, decimal_places=2, default=10)
    location = models.CharField('存放位置', max_length=100, blank=True)
    remark = models.TextField('备注', blank=True)
    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_goods'
        verbose_name = '货物'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    @property
    def is_warning(self):
        """是否预警"""
        return self.quantity <= self.warning_threshold


class StockIn(models.Model):
    """入库记录模型"""
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='stock_ins', verbose_name='货物'
    )
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='stock_in_operations', verbose_name='操作人'
    )
    quantity = models.DecimalField('入库数量', max_digits=12, decimal_places=2)
    batch_no = models.CharField('批次号', max_length=50, blank=True)
    supplier = models.CharField('供应商', max_length=200, blank=True)
    stock_in_time = models.DateTimeField('入库时间', auto_now_add=True)
    remark = models.TextField('备注', blank=True)
    
    class Meta:
        db_table = 'wh_stock_in'
        verbose_name = '入库记录'
        verbose_name_plural = verbose_name
        ordering = ['-stock_in_time']
    
    def __str__(self):
        return f"{self.goods.name} - {self.quantity}"


class StockOut(models.Model):
    """出库记录模型"""
    STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已通过'),
        ('rejected', '已拒绝'),
        ('completed', '已完成'),
    ]
    
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='stock_outs', verbose_name='货物'
    )
    operator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='stock_out_operations', verbose_name='操作人'
    )
    receiver = models.CharField('领用人', max_length=100)
    receiver_dept = models.CharField('领用部门', max_length=100, blank=True)
    quantity = models.DecimalField('出库数量', max_digits=12, decimal_places=2)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    stock_out_time = models.DateTimeField('出库时间', null=True, blank=True)
    remark = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    
    class Meta:
        db_table = 'wh_stock_out'
        verbose_name = '出库记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.goods.name} - {self.quantity}"


class Warning(models.Model):
    """预警记录模型"""
    TYPE_CHOICES = [
        ('low_stock', '库存不足'),
        ('expiring', '即将过期'),
        ('expired', '已过期'),
    ]
    
    goods = models.ForeignKey(
        Goods, on_delete=models.CASCADE,
        related_name='warnings', verbose_name='货物'
    )
    type = models.CharField('预警类型', max_length=20, choices=TYPE_CHOICES)
    message = models.TextField('预警信息')
    is_read = models.BooleanField('是否已读', default=False)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    
    class Meta:
        db_table = 'wh_warning'
        verbose_name = '预警记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.goods.name} - {self.get_type_display()}"


class Approval(models.Model):
    """审批记录模型"""
    STATUS_CHOICES = [
        ('pending', '待审批'),
        ('approved', '已通过'),
        ('rejected', '已拒绝'),
    ]
    
    stock_out = models.ForeignKey(
        StockOut, on_delete=models.CASCADE,
        related_name='approvals', verbose_name='出库记录'
    )
    approver = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='approvals', verbose_name='审批人'
    )
    status = models.CharField('审批状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    remark = models.TextField('审批意见', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    
    class Meta:
        db_table = 'wh_approval'
        verbose_name = '审批记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.stock_out} - {self.get_status_display()}"


# ==================== 移交单位准入管理 ====================

class TransferUnit(models.Model):
    """移交单位（外部送交受控物资的单位）"""
    STATUS_CHOICES = [
        ('active', '合作中'),
        ('suspended', '已暂停'),
        ('terminated', '已终止'),
    ]

    code = models.CharField('单位编号', max_length=50, unique=True)
    name = models.CharField('当前单位名称', max_length=100)
    status = models.CharField('合作状态', max_length=20, choices=STATUS_CHOICES, default='active')
    suspend_reason = models.CharField('暂停/终止原因', max_length=200, blank=True)
    suspended_at = models.DateTimeField('暂停时间', null=True, blank=True)
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
        """是否被暂停合作（终止合作同样不得发起新移交）"""
        return self.status in ('suspended', 'terminated')

    @property
    def historical_names(self):
        """曾用名（不含当前名称）"""
        return [
            record.name for record in self.name_records.all()
            if record.name != self.name
        ]


class TransferUnitNameRecord(models.Model):
    """移交单位名称变更记录（版本），任一历史名称只能对应一个单位"""
    unit = models.ForeignKey(
        TransferUnit, on_delete=models.CASCADE,
        related_name='name_records', verbose_name='移交单位'
    )
    name = models.CharField('单位名称', max_length=100, unique=True)
    effective_from = models.DateField('启用日期')
    reason = models.CharField('变更原因', max_length=200, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_unit_name_records', verbose_name='登记人'
    )
    created_at = models.DateTimeField('登记时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_transfer_unit_name'
        verbose_name = '移交单位名称记录'
        verbose_name_plural = verbose_name
        ordering = ['-effective_from', '-id']

    def __str__(self):
        return f"{self.unit.name} - {self.name}（{self.effective_from}起）"


class Authorization(models.Model):
    """移交授权或许可（准入版本）"""
    KIND_CHOICES = [
        ('regular', '常规授权'),
        ('emergency', '紧急临时许可'),
    ]

    unit = models.ForeignKey(
        TransferUnit, on_delete=models.CASCADE,
        related_name='authorizations', verbose_name='移交单位'
    )
    kind = models.CharField('准入类型', max_length=20, choices=KIND_CHOICES, default='regular')
    document_no = models.CharField('批准文号', max_length=100, blank=True)
    categories = models.ManyToManyField(
        Category, related_name='authorizations', verbose_name='授权品类范围'
    )
    valid_from = models.DateField('有效期开始')
    valid_to = models.DateField('有效期截止')
    revoked_at = models.DateTimeField('撤销时间', null=True, blank=True)
    revoke_reason = models.CharField('撤销原因', max_length=200, blank=True)
    remark = models.TextField('备注', blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='created_authorizations', verbose_name='批准人'
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'wh_authorization'
        verbose_name = '准入授权'
        verbose_name_plural = verbose_name
        ordering = ['-valid_from', '-id']

    def __str__(self):
        return f"{self.unit.name}-{self.get_kind_display()}-{self.valid_from}~{self.valid_to}"

    @property
    def is_revoked(self):
        return self.revoked_at is not None

    def covers(self, category, on_date):
        """该版本是否在指定日期覆盖指定品类（不含撤销判断之外的过滤）"""
        if self.is_revoked:
            return False
        if not (self.valid_from <= on_date <= self.valid_to):
            return False
        return self.categories.filter(pk=category.pk).exists()


class ReturnApproval(models.Model):
    """退回批准单：暂停合作的单位仅能凭已批准的退回单完成退回"""
    STATUS_CHOICES = [
        ('approved', '已批准'),
        ('used', '已使用'),
        ('cancelled', '已取消'),
    ]

    unit = models.ForeignKey(
        TransferUnit, on_delete=models.CASCADE,
        related_name='return_approvals', verbose_name='移交单位'
    )
    document_no = models.CharField('退回批准单号', max_length=100)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, null=True, blank=True,
        related_name='return_approvals', verbose_name='退回品类（空为不限）'
    )
    quantity = models.DecimalField('批准退回数量', max_digits=12, decimal_places=2, null=True, blank=True)
    reason = models.CharField('退回原因', max_length=200, blank=True)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='approved')
    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='approved_returns', verbose_name='批准人'
    )
    approved_at = models.DateTimeField('批准时间', auto_now_add=True)
    used_at = models.DateTimeField('使用时间', null=True, blank=True)
    used_handover = models.ForeignKey(
        'Handover', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='consumed_return_approvals', verbose_name='关联接收记录'
    )

    class Meta:
        db_table = 'wh_return_approval'
        verbose_name = '退回批准单'
        verbose_name_plural = verbose_name
        ordering = ['-approved_at']
        unique_together = ['unit', 'document_no']

    def __str__(self):
        return f"{self.unit.name}-退回单{self.document_no}"

    @property
    def is_usable(self):
        return self.status == 'approved'

    def matches_category(self, category):
        return self.category_id is None or self.category_id == category.pk


class Handover(models.Model):
    """移交接收记录（正式台账）：登记每次接收通过或拒绝及其判定依据"""
    PURPOSE_CHOICES = [
        ('handover', '新移交'),
        ('return', '退回'),
    ]
    DECISION_CHOICES = [
        ('accepted', '接收通过'),
        ('rejected', '接收拒绝'),
    ]

    unit = models.ForeignKey(
        TransferUnit, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='handovers', verbose_name='移交单位'
    )
    unit_name_snapshot = models.CharField('送交时填报单位名称', max_length=100)
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='handovers', verbose_name='物资品类'
    )
    variety = models.ForeignKey(
        Variety, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='handovers', verbose_name='物资品种'
    )
    material_name = models.CharField('物资名称', max_length=200, blank=True)
    material_code = models.CharField('物资编码', max_length=50, blank=True)
    quantity = models.DecimalField('数量', max_digits=12, decimal_places=2, default=0)
    batch_no = models.CharField('批次号', max_length=50, blank=True)
    purpose = models.CharField('业务类型', max_length=20, choices=PURPOSE_CHOICES, default='handover')
    decision = models.CharField('接收结论', max_length=20, choices=DECISION_CHOICES)
    handover_date = models.DateField('接收判定日期')
    authorization = models.ForeignKey(
        Authorization, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='handovers', verbose_name='适用准入版本'
    )
    return_approval = models.ForeignKey(
        ReturnApproval, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='handovers', verbose_name='退回批准单'
    )
    basis = models.TextField('判定依据')
    reject_reason = models.CharField('拒绝原因', max_length=200, blank=True)
    received_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='received_handovers', verbose_name='值班员'
    )
    created_at = models.DateTimeField('登记时间', auto_now_add=True)

    class Meta:
        db_table = 'wh_handover'
        verbose_name = '移交接收记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.unit_name_snapshot}-{self.get_decision_display()}"
