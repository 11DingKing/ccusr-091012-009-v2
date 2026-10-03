"""
移交单位与准入管理序列化器
"""
from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from .models import Category, Goods
from .access_models import (
    AccessGrant, CustodyTransfer, EmergencyPermit, ReturnApproval,
    TransferUnit, UnitNameChange,
)


class UnitNameChangeSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    is_effective = serializers.BooleanField(read_only=True)

    class Meta:
        model = UnitNameChange
        fields = [
            'id', 'unit', 'previous_name', 'current_name', 'effective_from',
            'reason', 'is_effective', 'created_by', 'created_by_name', 'created_at',
        ]
        read_only_fields = ['id', 'current_name', 'created_at']


class TransferUnitSerializer(serializers.ModelSerializer):
    is_suspended = serializers.BooleanField(read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    name_changes = UnitNameChangeSerializer(many=True, read_only=True)

    class Meta:
        model = TransferUnit
        fields = [
            'id', 'name', 'status', 'status_display', 'is_suspended',
            'suspended_at', 'suspend_reason',
            'created_by', 'created_by_name', 'created_at', 'updated_at', 'name_changes',
        ]
        read_only_fields = ['id', 'suspended_at', 'created_at', 'updated_at']


class TransferUnitWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=True)
    status = serializers.ChoiceField(
        choices=[TransferUnit.STATUS_ACTIVE, TransferUnit.STATUS_SUSPENDED],
        required=False,
    )
    suspend_reason = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('单位名称不能为空')
        instance = self.context.get('instance')
        qs = TransferUnit.objects.filter(name=value)
        if instance:
            qs = qs.exclude(pk=instance.pk)
        if qs.exists():
            raise serializers.ValidationError('移交单位名称已存在')
        return value


class NameChangeCreateSerializer(serializers.Serializer):
    previous_name = serializers.CharField(max_length=100, required=True)
    effective_from = serializers.DateTimeField(required=False)
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate_previous_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('曾用名不能为空')
        return value

    def validate(self, data):
        unit = self.context['unit']
        if data['previous_name'] == unit.name:
            raise serializers.ValidationError({'previous_name': '曾用名不能与当前名称相同'})
        # 曾用名不得与任何现存单位的当前名称冲突，避免解析歧义
        if TransferUnit.objects.filter(name=data['previous_name']).exists():
            raise serializers.ValidationError({'previous_name': '该名称已是现存单位的当前名称，会造成身份歧义'})
        if unit.name_changes.filter(previous_name=data['previous_name']).exists():
            raise serializers.ValidationError({'previous_name': '该曾用名已登记过'})
        if 'effective_from' not in data:
            data['effective_from'] = timezone.now()
        return data


class AccessGrantSerializer(serializers.ModelSerializer):
    scope_type_display = serializers.CharField(source='get_scope_type_display', read_only=True)
    category_names = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    in_effect_now = serializers.SerializerMethodField()

    class Meta:
        model = AccessGrant
        fields = [
            'id', 'unit', 'scope_type', 'scope_type_display', 'categories', 'category_names',
            'effective_from', 'effective_to', 'version_no', 'remark', 'is_active',
            'in_effect_now', 'created_by', 'created_by_name', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_category_names(self, obj):
        return [{'id': cid, 'name': cname} for cid, cname in obj.categories.values_list('id', 'name')]

    def get_in_effect_now(self, obj):
        return obj.in_effect()


class AccessGrantWriteSerializer(serializers.Serializer):
    unit = serializers.IntegerField(required=True)
    scope_type = serializers.ChoiceField(
        choices=[AccessGrant.SCOPE_ALL, AccessGrant.SCOPE_SPECIFIED], required=False,
    )
    categories = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_empty=True
    )
    effective_from = serializers.DateTimeField(required=False, allow_null=True)
    effective_to = serializers.DateTimeField(required=False, allow_null=True)
    version_no = serializers.CharField(max_length=50, required=False, allow_blank=True)
    remark = serializers.CharField(max_length=200, required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)

    def validate_unit(self, value):
        if not TransferUnit.objects.filter(pk=value).exists():
            raise serializers.ValidationError('移交单位不存在')
        return value

    def validate(self, data):
        data.setdefault('scope_type', AccessGrant.SCOPE_SPECIFIED)
        category_ids = data.get('categories') or []
        if category_ids:
            found = set(Category.objects.filter(pk__in=category_ids).values_list('id', flat=True))
            missing = set(category_ids) - found
            if missing:
                raise serializers.ValidationError({'categories': f'品类不存在：{sorted(missing)}'})
        if data['scope_type'] == AccessGrant.SCOPE_SPECIFIED and not category_ids:
            raise serializers.ValidationError({'categories': '指定品类范围时必须选择至少一个品类'})
        start, end = data.get('effective_from'), data.get('effective_to')
        if start and end and start > end:
            raise serializers.ValidationError({'effective_to': '失效日期不能早于生效日期'})
        return data


class EmergencyPermitSerializer(serializers.ModelSerializer):
    scope_type_display = serializers.CharField(source='get_scope_type_display', read_only=True)
    category_names = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    in_effect_now = serializers.SerializerMethodField()
    remaining_uses = serializers.SerializerMethodField()

    class Meta:
        model = EmergencyPermit
        fields = [
            'id', 'unit', 'reason', 'scope_type', 'scope_type_display', 'categories',
            'category_names', 'valid_from', 'valid_to', 'approved_by',
            'used_count', 'max_uses', 'remaining_uses', 'is_revoked',
            'in_effect_now', 'remark', 'created_by', 'created_by_name', 'created_at',
        ]
        read_only_fields = ['id', 'used_count', 'created_at']

    def get_category_names(self, obj):
        return [{'id': cid, 'name': cname} for cid, cname in obj.categories.values_list('id', 'name')]

    def get_in_effect_now(self, obj):
        return obj.in_effect()

    def get_remaining_uses(self, obj):
        if obj.max_uses is None:
            return None
        return max(0, obj.max_uses - obj.used_count)


class EmergencyPermitWriteSerializer(serializers.Serializer):
    unit = serializers.IntegerField(required=True)
    reason = serializers.CharField(max_length=200, required=True)
    scope_type = serializers.ChoiceField(
        choices=[AccessGrant.SCOPE_ALL, AccessGrant.SCOPE_SPECIFIED], required=False,
    )
    categories = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_empty=True
    )
    valid_from = serializers.DateTimeField(required=True)
    valid_to = serializers.DateTimeField(required=True)
    approved_by = serializers.CharField(max_length=50, required=True)
    max_uses = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    remark = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate_unit(self, value):
        if not TransferUnit.objects.filter(pk=value).exists():
            raise serializers.ValidationError('移交单位不存在')
        return value

    def validate(self, data):
        data.setdefault('scope_type', AccessGrant.SCOPE_SPECIFIED)
        if data['valid_from'] > data['valid_to']:
            raise serializers.ValidationError({'valid_to': '有效期截止不能早于开始时间'})
        category_ids = data.get('categories') or []
        if category_ids:
            found = set(Category.objects.filter(pk__in=category_ids).values_list('id', flat=True))
            missing = set(category_ids) - found
            if missing:
                raise serializers.ValidationError({'categories': f'品类不存在：{sorted(missing)}'})
        if data['scope_type'] == AccessGrant.SCOPE_SPECIFIED and not category_ids:
            raise serializers.ValidationError({'categories': '指定品类范围时必须选择至少一个品类'})
        return data


class ReturnApprovalSerializer(serializers.ModelSerializer):
    unit_name = serializers.CharField(source='unit.name', read_only=True)
    goods_name = serializers.CharField(source='goods.name', read_only=True, default='')
    remaining_quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True
    )
    in_effect_now = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = ReturnApproval
        fields = [
            'id', 'unit', 'unit_name', 'approval_no', 'goods', 'goods_name',
            'approved_quantity', 'used_quantity', 'remaining_quantity',
            'valid_from', 'valid_to', 'is_revoked', 'in_effect_now',
            'remark', 'created_by', 'created_by_name', 'created_at',
        ]
        read_only_fields = ['id', 'used_quantity', 'created_at']

    def get_in_effect_now(self, obj):
        return obj.in_effect()


class ReturnApprovalWriteSerializer(serializers.Serializer):
    unit = serializers.IntegerField(required=True)
    approval_no = serializers.CharField(max_length=50, required=True)
    goods = serializers.IntegerField(required=False, allow_null=True)
    approved_quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=True, min_value=Decimal('0.01')
    )
    valid_from = serializers.DateTimeField(required=False, allow_null=True)
    valid_to = serializers.DateTimeField(required=False, allow_null=True)
    remark = serializers.CharField(max_length=200, required=False, allow_blank=True)

    def validate_unit(self, value):
        if not TransferUnit.objects.filter(pk=value).exists():
            raise serializers.ValidationError('移交单位不存在')
        return value

    def validate_approval_no(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('批准文号不能为空')
        if ReturnApproval.objects.filter(approval_no=value).exists():
            instance = self.context.get('instance')
            if not instance or instance.approval_no != value:
                raise serializers.ValidationError('批准文号已存在')
        return value

    def validate_goods(self, value):
        if value and not Goods.objects.filter(pk=value).exists():
            raise serializers.ValidationError('货物不存在')
        return value

    def validate(self, data):
        start, end = data.get('valid_from'), data.get('valid_to')
        if start and end and start > end:
            raise serializers.ValidationError({'valid_to': '有效期截止不能早于开始时间'})
        return data


class ReceiveSerializer(serializers.Serializer):
    """收件提交序列化器"""
    unit_name = serializers.CharField(max_length=100, required=True)
    goods = serializers.IntegerField(required=True)
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=True, min_value=Decimal('0.01')
    )
    kind = serializers.ChoiceField(
        choices=[CustodyTransfer.KIND_HANDOVER, CustodyTransfer.KIND_RETURN], required=False
    )
    received_at = serializers.DateTimeField(required=False)
    return_approval_no = serializers.CharField(max_length=50, required=False, allow_blank=True)
    batch_no = serializers.CharField(max_length=50, required=False, allow_blank=True)
    remark = serializers.CharField(required=False, allow_blank=True)

    def validate_unit_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('请填写移交单位名称')
        return value

    def validate_goods(self, value):
        if not Goods.objects.filter(pk=value).exists():
            raise serializers.ValidationError('货物不存在')
        return value

    def validate(self, data):
        data.setdefault('kind', CustodyTransfer.KIND_HANDOVER)
        if data['kind'] == CustodyTransfer.KIND_RETURN and not data.get('return_approval_no'):
            raise serializers.ValidationError({'return_approval_no': '退回必须填写退回来件批准文号'})
        return data


class CustodyTransferSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source='get_kind_display', read_only=True)
    decision_display = serializers.CharField(source='get_decision_display', read_only=True)
    basis_type_display = serializers.CharField(source='get_basis_type_display', read_only=True)
    unit_name = serializers.CharField(source='unit.name', read_only=True, default='')
    goods_name = serializers.CharField(source='goods.name', read_only=True)
    category_name = serializers.CharField(source='goods.variety.category.name', read_only=True)
    operator_name = serializers.CharField(source='operator.username', read_only=True)

    class Meta:
        model = CustodyTransfer
        fields = [
            'id', 'kind', 'kind_display', 'goods', 'goods_name', 'category_name',
            'unit', 'unit_name', 'unit_name_used', 'quantity', 'received_at',
            'operator', 'operator_name', 'decision', 'decision_display',
            'basis_type', 'basis_type_display', 'grant', 'permit',
            'decision_basis', 'rejection_reason',
            'return_approval_no', 'batch_no', 'remark', 'created_at',
        ]
