"""
仓库管理序列化器
"""
from datetime import date

from rest_framework import serializers
from .models import (
    Approval, Authorization, Category, Goods, Handover, ReturnApproval,
    StockIn, StockOut, TransferUnit, TransferUnitNameRecord, Unit,
    Variety, Warning,
)


class UnitSerializer(serializers.ModelSerializer):
    """单位序列化器"""
    is_linked = serializers.BooleanField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    
    class Meta:
        model = Unit
        fields = [
            'id', 'name', 'is_linked', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class UnitCreateSerializer(serializers.Serializer):
    """单位创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=5, required=True, error_messages={
        'required': '请输入单位名称',
        'blank': '单位名称不能为空',
        'min_length': '单位名称至少1个字',
        'max_length': '单位名称最多5个字',
    })
    
    def validate_name(self, value):
        instance = self.context.get('instance')
        if instance:
            if Unit.objects.filter(name=value).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('单位名称已存在')
        else:
            if Unit.objects.filter(name=value).exists():
                raise serializers.ValidationError('单位名称已存在')
        return value


class CategorySerializer(serializers.ModelSerializer):
    """品类序列化器"""
    is_linked = serializers.BooleanField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    unit_name = serializers.CharField(source='unit.name', read_only=True)
    
    class Meta:
        model = Category
        fields = [
            'id', 'name', 'unit', 'unit_name', 'is_linked', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class CategoryCreateSerializer(serializers.Serializer):
    """品类创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=10, required=True, error_messages={
        'required': '请输入品类名称',
        'blank': '品类名称不能为空',
        'min_length': '品类名称至少1个字',
        'max_length': '品类名称最多10个字',
    })
    unit = serializers.IntegerField(required=True, error_messages={
        'required': '请选择单位',
    })
    
    def validate_name(self, value):
        instance = self.context.get('instance')
        if instance:
            if Category.objects.filter(name=value).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('品类名称已存在')
        else:
            if Category.objects.filter(name=value).exists():
                raise serializers.ValidationError('品类名称已存在')
        return value
    
    def validate_unit(self, value):
        if not Unit.objects.filter(pk=value).exists():
            raise serializers.ValidationError('单位不存在')
        return value


class VarietySerializer(serializers.ModelSerializer):
    """品种序列化器"""
    is_in_stock = serializers.BooleanField(read_only=True)
    unit_name = serializers.CharField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    
    class Meta:
        model = Variety
        fields = [
            'id', 'name', 'category', 'category_name', 'unit_name',
            'is_in_stock', 'is_active',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class VarietyCreateSerializer(serializers.Serializer):
    """品种创建序列化器"""
    name = serializers.CharField(min_length=1, max_length=20, required=True, error_messages={
        'required': '请输入品种名称',
        'blank': '品种名称不能为空',
        'min_length': '品种名称至少1个字',
        'max_length': '品种名称最多20个字',
    })
    category = serializers.IntegerField(required=True, error_messages={
        'required': '请选择品类',
    })
    
    def validate_category(self, value):
        if not Category.objects.filter(pk=value).exists():
            raise serializers.ValidationError('品类不存在')
        return value
    
    def validate(self, data):
        instance = self.context.get('instance')
        name = data['name']
        category_id = data['category']
        
        if instance:
            if Variety.objects.filter(name=name, category_id=category_id).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError('该品类下已存在同名品种')
        else:
            if Variety.objects.filter(name=name, category_id=category_id).exists():
                raise serializers.ValidationError('该品类下已存在同名品种')
        return data


class GoodsSerializer(serializers.ModelSerializer):
    """货物序列化器"""
    variety_name = serializers.CharField(source='variety.name', read_only=True)
    category_name = serializers.CharField(source='variety.category.name', read_only=True)
    unit_name = serializers.CharField(source='variety.category.unit.name', read_only=True)
    is_warning = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Goods
        fields = [
            'id', 'name', 'code', 'variety', 'variety_name',
            'category_name', 'unit_name', 'specification',
            'quantity', 'warning_threshold', 'location',
            'remark', 'is_active', 'is_warning',
            'created_at', 'updated_at'
        ]


class StockInSerializer(serializers.ModelSerializer):
    """入库记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    
    class Meta:
        model = StockIn
        fields = [
            'id', 'goods', 'goods_name', 'operator', 'operator_name',
            'quantity', 'batch_no', 'supplier', 'stock_in_time', 'remark'
        ]


class StockOutSerializer(serializers.ModelSerializer):
    """出库记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = StockOut
        fields = [
            'id', 'goods', 'goods_name', 'operator', 'operator_name',
            'receiver', 'receiver_dept', 'quantity', 'status', 'status_display',
            'stock_out_time', 'remark', 'created_at'
        ]


class WarningSerializer(serializers.ModelSerializer):
    """预警记录序列化器"""
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    
    class Meta:
        model = Warning
        fields = [
            'id', 'goods', 'goods_name', 'type', 'type_display',
            'message', 'is_read', 'created_at'
        ]


class ApprovalSerializer(serializers.ModelSerializer):
    """审批记录序列化器"""
    approver_name = serializers.CharField(source='approver.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Approval
        fields = [
            'id', 'stock_out', 'approver', 'approver_name',
            'status', 'status_display', 'remark', 'created_at', 'updated_at'
        ]


# ==================== 移交单位准入管理 ====================

class TransferUnitNameRecordSerializer(serializers.ModelSerializer):
    """移交单位名称记录序列化器"""
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = TransferUnitNameRecord
        fields = [
            'id', 'unit', 'name', 'effective_from', 'reason',
            'created_by', 'created_by_name', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class TransferUnitSerializer(serializers.ModelSerializer):
    """移交单位序列化器"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_suspended = serializers.BooleanField(read_only=True)
    historical_names = serializers.JSONField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    name_records = TransferUnitNameRecordSerializer(many=True, read_only=True)

    class Meta:
        model = TransferUnit
        fields = [
            'id', 'code', 'name', 'status', 'status_display', 'suspend_reason',
            'suspended_at', 'is_suspended', 'historical_names', 'name_records',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'suspended_at', 'created_at', 'updated_at']


class TransferUnitCreateSerializer(serializers.Serializer):
    """移交单位创建序列化器"""
    code = serializers.CharField(max_length=50, required=True, error_messages={
        'required': '请输入单位编号', 'blank': '单位编号不能为空',
    })
    name = serializers.CharField(min_length=1, max_length=100, required=True, error_messages={
        'required': '请输入单位名称', 'blank': '单位名称不能为空',
        'max_length': '单位名称最多100个字',
    })

    def validate_code(self, value):
        value = value.strip()
        if TransferUnit.objects.filter(code=value).exists():
            raise serializers.ValidationError('单位编号已存在')
        return value

    def validate_name(self, value):
        value = value.strip()
        if TransferUnit.objects.filter(name=value).exists():
            raise serializers.ValidationError('单位名称已被当前在册单位使用')
        if TransferUnitNameRecord.objects.filter(name=value).exists():
            raise serializers.ValidationError('该名称已被其他单位登记为历史名称')
        return value


class UnitRenameSerializer(serializers.Serializer):
    """移交单位名称变更序列化器"""
    new_name = serializers.CharField(min_length=1, max_length=100, required=True, error_messages={
        'required': '请输入新单位名称', 'blank': '新单位名称不能为空',
    })
    effective_from = serializers.DateField(required=True, error_messages={
        'required': '请选择名称生效日期', 'invalid': '生效日期格式不正确',
    })
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate_new_name(self, value):
        value = value.strip()
        if TransferUnit.objects.filter(name=value).exists():
            raise serializers.ValidationError('该名称已被其他在册单位使用')
        if TransferUnitNameRecord.objects.filter(name=value).exists():
            raise serializers.ValidationError('该名称已被登记为单位名称（含历史名称）')
        return value


class UnitStatusSerializer(serializers.Serializer):
    """移交单位暂停/恢复序列化器"""
    status = serializers.ChoiceField(choices=['active', 'suspended', 'terminated'], required=True)
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True)


class AuthorizationSerializer(serializers.ModelSerializer):
    """准入授权序列化器"""
    kind_display = serializers.CharField(source='get_kind_display', read_only=True)
    unit_name = serializers.CharField(source='unit.name', read_only=True)
    is_revoked = serializers.BooleanField(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    category_ids = serializers.SerializerMethodField()

    class Meta:
        model = Authorization
        fields = [
            'id', 'unit', 'unit_name', 'kind', 'kind_display', 'document_no',
            'categories', 'category_ids', 'valid_from', 'valid_to',
            'is_revoked', 'revoked_at', 'revoke_reason', 'remark',
            'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'revoked_at', 'created_at', 'updated_at']
        extra_kwargs = {'categories': {'write_only': True}}

    def get_category_ids(self, obj):
        return list(obj.categories.values_list('id', flat=True))


class AuthorizationWriteSerializer(serializers.Serializer):
    """准入授权创建/更新序列化器"""
    unit = serializers.IntegerField(required=True, error_messages={'required': '请选择移交单位'})
    kind = serializers.ChoiceField(choices=['regular', 'emergency'], default='regular')
    document_no = serializers.CharField(max_length=100, required=False, allow_blank=True)
    category_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=False,
        error_messages={'required': '请选择授权品类范围', 'empty': '授权品类范围不能为空'},
    )
    valid_from = serializers.DateField(required=True, error_messages={'required': '请选择有效期开始日期'})
    valid_to = serializers.DateField(required=True, error_messages={'required': '请选择有效期截止日期'})
    remark = serializers.CharField(required=False, allow_blank=True)

    def validate_unit(self, value):
        if not TransferUnit.objects.filter(pk=value).exists():
            raise serializers.ValidationError('移交单位不存在')
        return value

    def validate_category_ids(self, value):
        categories = list(Category.objects.filter(pk__in=value))
        if len(categories) != len(set(value)):
            raise serializers.ValidationError('授权品类存在重复')
        if len(categories) != len(value):
            raise serializers.ValidationError('存在无效的授权品类')
        return value

    def validate(self, data):
        if data['valid_to'] < data['valid_from']:
            raise serializers.ValidationError('有效期截止日期不能早于开始日期')
        return data


class AuthorizationRevokeSerializer(serializers.Serializer):
    """授权撤销序列化器"""
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True)


class ReturnApprovalSerializer(serializers.ModelSerializer):
    """退回批准单序列化器"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_usable = serializers.BooleanField(read_only=True)
    unit_name = serializers.CharField(source='unit.name', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.username', read_only=True)

    class Meta:
        model = ReturnApproval
        fields = [
            'id', 'unit', 'unit_name', 'document_no', 'category', 'category_name',
            'quantity', 'reason', 'status', 'status_display', 'is_usable',
            'approved_by', 'approved_by_name', 'approved_at', 'used_at',
        ]
        read_only_fields = ['id', 'status', 'approved_at', 'used_at']


class ReturnApprovalWriteSerializer(serializers.Serializer):
    """退回批准单创建序列化器"""
    unit = serializers.IntegerField(required=True, error_messages={'required': '请选择移交单位'})
    document_no = serializers.CharField(max_length=100, required=True, error_messages={
        'required': '请输入退回批准单号', 'blank': '退回批准单号不能为空',
    })
    category = serializers.IntegerField(required=False, allow_null=True)
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True, min_value=0,
    )
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate_unit(self, value):
        if not TransferUnit.objects.filter(pk=value).exists():
            raise serializers.ValidationError('移交单位不存在')
        return value

    def validate_category(self, value):
        if value is not None and not Category.objects.filter(pk=value).exists():
            raise serializers.ValidationError('品类不存在')
        return value

    def validate(self, data):
        if ReturnApproval.objects.filter(
            unit_id=data['unit'], document_no=data['document_no']
        ).exists():
            raise serializers.ValidationError('该单位下退回批准单号已存在')
        return data


class AdmissionEvaluateSerializer(serializers.Serializer):
    """收件准入判定（预检，不登记台账）序列化器"""
    unit_name = serializers.CharField(max_length=100, required=True, error_messages={
        'required': '请输入送交单位名称', 'blank': '送交单位名称不能为空',
    })
    category = serializers.IntegerField(required=True, error_messages={'required': '请选择物资品类'})
    on_date = serializers.DateField(required=False)
    purpose = serializers.ChoiceField(choices=['handover', 'return'], default='handover')
    return_document_no = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def validate_unit_name(self, value):
        return value.strip()

    def validate_category(self, value):
        if not Category.objects.filter(pk=value).exists():
            raise serializers.ValidationError('物资品类不存在')
        return value

    def validate(self, data):
        data.setdefault('on_date', date.today())
        if data.get('purpose') == 'return' and not data.get('return_document_no'):
            raise serializers.ValidationError('退回业务必须提供退回批准单号')
        return data


class HandoverReceiveSerializer(serializers.Serializer):
    """正式接收登记序列化器：先判定，通过方可写入正式台账"""
    unit_name = serializers.CharField(max_length=100, required=True, error_messages={
        'required': '请输入送交单位名称', 'blank': '送交单位名称不能为空',
    })
    category = serializers.IntegerField(required=True, error_messages={'required': '请选择物资品类'})
    variety = serializers.IntegerField(required=False, allow_null=True)
    material_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    material_code = serializers.CharField(max_length=50, required=False, allow_blank=True)
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, default=0, min_value=0,
    )
    batch_no = serializers.CharField(max_length=50, required=False, allow_blank=True)
    on_date = serializers.DateField(required=False)
    purpose = serializers.ChoiceField(choices=['handover', 'return'], default='handover')
    return_document_no = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def validate_unit_name(self, value):
        return value.strip()

    def validate_category(self, value):
        if not Category.objects.filter(pk=value).exists():
            raise serializers.ValidationError('物资品类不存在')
        return value

    def validate_variety(self, value):
        if value is not None and not Variety.objects.filter(pk=value).exists():
            raise serializers.ValidationError('物资品种不存在')
        return value

    def validate(self, data):
        data.setdefault('on_date', date.today())
        if data.get('purpose') == 'return' and not data.get('return_document_no'):
            raise serializers.ValidationError('退回业务必须提供退回批准单号')
        variety_id = data.get('variety')
        if variety_id and not Variety.objects.filter(
            pk=variety_id, category_id=data['category']
        ).exists():
            raise serializers.ValidationError('物资品种不属于所选物资品类')
        return data


class HandoverSerializer(serializers.ModelSerializer):
    """移交接收记录序列化器"""
    purpose_display = serializers.CharField(source='get_purpose_display', read_only=True)
    decision_display = serializers.CharField(source='get_decision_display', read_only=True)
    unit_name = serializers.SerializerMethodField()
    category_name = serializers.CharField(source='category.name', read_only=True)
    received_by_name = serializers.CharField(source='received_by.username', read_only=True)
    authorization_kind = serializers.SerializerMethodField()
    authorization_document = serializers.SerializerMethodField()
    basis_lines = serializers.SerializerMethodField()

    class Meta:
        model = Handover
        fields = [
            'id', 'unit', 'unit_name', 'unit_name_snapshot', 'category', 'category_name',
            'variety', 'material_name', 'material_code', 'quantity', 'batch_no',
            'purpose', 'purpose_display', 'decision', 'decision_display', 'handover_date',
            'authorization', 'authorization_kind', 'authorization_document',
            'return_approval', 'basis', 'basis_lines', 'reject_reason',
            'received_by', 'received_by_name', 'created_at',
        ]

    def get_unit_name(self, obj):
        return obj.unit.name if obj.unit else ''

    def get_authorization_kind(self, obj):
        return obj.authorization.get_kind_display() if obj.authorization else ''

    def get_authorization_document(self, obj):
        return obj.authorization.document_no if obj.authorization else ''

    def get_basis_lines(self, obj):
        return [line for line in (obj.basis or '').splitlines() if line.strip()]
