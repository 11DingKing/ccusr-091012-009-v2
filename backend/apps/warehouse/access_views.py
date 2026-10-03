"""
移交单位准入管理视图

路由前缀：/api/
- transfer-units/             移交单位台账
- access-grants/              准入授权版本
- emergency-permits/          紧急临时许可
- return-approvals/           退回来件批准
- custody/check/              收件前准入试判（不落库，返回判定依据）
- custody/receive/            正式收件（判定 + 登记台账）
- custody/transfers/          移交/退回台账查询（含每次通过或拒绝的具体依据）
"""
import logging

from django.db.models import Q
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from apps.core.response import success_response, error_response
from .models import Goods
from .access_models import (
    AccessGrant, CustodyTransfer, EmergencyPermit, ReturnApproval,
    TransferUnit, UnitNameChange,
)
from .access_control import evaluate_admission, receive_transfer
from .access_serializers import (
    AccessGrantSerializer, AccessGrantWriteSerializer,
    CustodyTransferSerializer, EmergencyPermitSerializer, EmergencyPermitWriteSerializer,
    NameChangeCreateSerializer, ReceiveSerializer, ReturnApprovalSerializer,
    ReturnApprovalWriteSerializer, TransferUnitSerializer, TransferUnitWriteSerializer,
    UnitNameChangeSerializer,
)

logger = logging.getLogger('apps')


def _first_error(errors):
    first = list(errors.values())[0]
    if isinstance(first, list):
        first = first[0]
    return str(first)


def _paginate(request, queryset):
    try:
        page = max(int(request.query_params.get('page', 1)), 1)
        page_size = max(int(request.query_params.get('page_size', 10)), 1)
    except (TypeError, ValueError):
        page, page_size = 1, 10
    total = queryset.count()
    return queryset[(page - 1) * page_size:page * page_size], total, page, page_size


# ==================== 移交单位 ====================

class TransferUnitListView(APIView):
    """移交单位列表/新建"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = TransferUnit.objects.all().prefetch_related('name_changes')
        name = request.query_params.get('name')
        if name:
            queryset = queryset.filter(name__icontains=name)
        status = request.query_params.get('status')
        if status in (TransferUnit.STATUS_ACTIVE, TransferUnit.STATUS_SUSPENDED):
            queryset = queryset.filter(status=status)
        queryset = queryset.order_by('-created_at')

        items, total, page, page_size = _paginate(request, queryset)
        return success_response(data={
            'list': TransferUnitSerializer(items, many=True).data,
            'total': total, 'page': page, 'page_size': page_size,
        })

    def post(self, request):
        serializer = TransferUnitWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))
        data = serializer.validated_data
        unit = TransferUnit(name=data['name'], created_by=request.user)
        if data.get('status') == TransferUnit.STATUS_SUSPENDED:
            unit.status = TransferUnit.STATUS_SUSPENDED
            unit.suspend_reason = data.get('suspend_reason', '')
            unit.suspended_at = timezone.now()
        unit.save()
        logger.info("用户 %s 创建移交单位 %s", request.user.username, unit.name)
        return success_response(data=TransferUnitSerializer(unit).data, message='创建成功')


class TransferUnitAllView(APIView):
    """移交单位下拉（含暂停标记，供收件选择时提示）"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        units = TransferUnit.objects.all().order_by('name')
        return success_response(data=TransferUnitSerializer(units, many=True).data)


class TransferUnitDetailView(APIView):
    """移交单位详情/更名（更名自动登记名称变更链）"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        unit = TransferUnit.objects.prefetch_related('name_changes').filter(pk=pk).first()
        if not unit:
            return error_response(message='移交单位不存在', code=404)
        return success_response(data=TransferUnitSerializer(unit).data)

    def put(self, request, pk):
        unit = TransferUnit.objects.filter(pk=pk).first()
        if not unit:
            return error_response(message='移交单位不存在', code=404)

        serializer = TransferUnitWriteSerializer(
            data=request.data, context={'instance': unit}
        )
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))

        data = serializer.validated_data
        old_name = unit.name
        new_name = data['name']
        if new_name != old_name:
            change = UnitNameChange(
                unit=unit, previous_name=old_name, current_name=new_name,
                reason='单位更名', created_by=request.user,
            )
            unit.name = new_name
            unit.save(update_fields=['name', 'updated_at'])
            change.save()
            logger.info("用户 %s 将单位 %s 更名为 %s", request.user.username, old_name, new_name)

        if 'status' in data:
            if data['status'] == TransferUnit.STATUS_SUSPENDED:
                if not unit.is_suspended:
                    unit.suspend(reason=data.get('suspend_reason', ''))
                elif data.get('suspend_reason'):
                    unit.suspend_reason = data['suspend_reason']
                    unit.save(update_fields=['suspend_reason', 'updated_at'])
            elif data['status'] == TransferUnit.STATUS_ACTIVE and unit.is_suspended:
                unit.resume()

        unit.refresh_from_db()
        return success_response(data=TransferUnitSerializer(unit).data, message='更新成功')


class TransferUnitSuspendView(APIView):
    """暂停合作"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        unit = TransferUnit.objects.filter(pk=pk).first()
        if not unit:
            return error_response(message='移交单位不存在', code=404)
        unit.suspend(reason=request.data.get('suspend_reason', ''))
        logger.info("用户 %s 暂停移交单位 %s", request.user.username, unit.name)
        return success_response(data=TransferUnitSerializer(unit).data, message='已暂停合作')


class TransferUnitResumeView(APIView):
    """恢复合作"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        unit = TransferUnit.objects.filter(pk=pk).first()
        if not unit:
            return error_response(message='移交单位不存在', code=404)
        unit.resume()
        logger.info("用户 %s 恢复移交单位 %s", request.user.username, unit.name)
        return success_response(data=TransferUnitSerializer(unit).data, message='已恢复合作')


class UnitNameChangeListView(APIView):
    """曾用名登记/查询"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        unit = TransferUnit.objects.filter(pk=pk).first()
        if not unit:
            return error_response(message='移交单位不存在', code=404)
        changes = unit.name_changes.all().order_by('-effective_from')
        return success_response(data=UnitNameChangeSerializer(changes, many=True).data)

    def post(self, request, pk):
        unit = TransferUnit.objects.filter(pk=pk).first()
        if not unit:
            return error_response(message='移交单位不存在', code=404)
        serializer = NameChangeCreateSerializer(data=request.data, context={'unit': unit})
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))
        data = serializer.validated_data
        change = UnitNameChange.objects.create(
            unit=unit, previous_name=data['previous_name'], current_name=unit.name,
            effective_from=data['effective_from'], reason=data.get('reason', ''),
            created_by=request.user,
        )
        logger.info("用户 %s 为单位 %s 登记曾用名 %s", request.user.username, unit.name, change.previous_name)
        return success_response(data=UnitNameChangeSerializer(change).data, message='曾用名登记成功')


# ==================== 准入授权 ====================

class AccessGrantListView(APIView):
    """准入授权版本列表/新建"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = AccessGrant.objects.all().prefetch_related('categories')
        unit_id = request.query_params.get('unit')
        if unit_id:
            queryset = queryset.filter(unit_id=unit_id)
        category_id = request.query_params.get('category')
        if category_id:
            queryset = queryset.filter(
                Q(scope_type=AccessGrant.SCOPE_ALL) | Q(categories=category_id)
            )
        is_active = request.query_params.get('is_active')
        if is_active in ('true', 'false'):
            queryset = queryset.filter(is_active=is_active == 'true')
        queryset = queryset.order_by('-effective_from', '-created_at')

        items, total, page, page_size = _paginate(request, queryset)
        return success_response(data={
            'list': AccessGrantSerializer(items, many=True).data,
            'total': total, 'page': page, 'page_size': page_size,
        })

    def post(self, request):
        serializer = AccessGrantWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))
        data = serializer.validated_data
        unit = TransferUnit.objects.get(pk=data['unit'])
        grant = AccessGrant.objects.create(
            unit=unit,
            scope_type=data['scope_type'],
            effective_from=data.get('effective_from'),
            effective_to=data.get('effective_to'),
            version_no=data.get('version_no', ''),
            remark=data.get('remark', ''),
            is_active=data.get('is_active', True),
            created_by=request.user,
        )
        if data['scope_type'] == AccessGrant.SCOPE_SPECIFIED:
            grant.categories.set(data['categories'])
        logger.info("用户 %s 为单位 %s 登记授权版本 #%s", request.user.username, unit.name, grant.pk)
        return success_response(data=AccessGrantSerializer(grant).data, message='创建成功')


class AccessGrantDetailView(APIView):
    """授权版本更新/作废删除"""
    permission_classes = [IsAuthenticated]

    def _get(self, pk):
        return AccessGrant.objects.prefetch_related('categories').filter(pk=pk).first()

    def put(self, request, pk):
        grant = self._get(pk)
        if not grant:
            return error_response(message='授权版本不存在', code=404)
        serializer = AccessGrantWriteSerializer(data=request.data, context={'instance': grant})
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))
        data = serializer.validated_data
        if grant.unit_id != data['unit']:
            grant.unit = TransferUnit.objects.get(pk=data['unit'])
        grant.scope_type = data['scope_type']
        grant.effective_from = data.get('effective_from')
        grant.effective_to = data.get('effective_to')
        grant.version_no = data.get('version_no', '')
        grant.remark = data.get('remark', '')
        if 'is_active' in data:
            grant.is_active = data['is_active']
        grant.save()
        if data['scope_type'] == AccessGrant.SCOPE_SPECIFIED:
            grant.categories.set(data['categories'])
        else:
            grant.categories.clear()
        return success_response(data=AccessGrantSerializer(self._get(pk)).data, message='更新成功')

    def delete(self, request, pk):
        grant = self._get(pk)
        if not grant:
            return error_response(message='授权版本不存在', code=404)
        if grant.transfers.exists():
            grant.is_active = False
            grant.save(update_fields=['is_active', 'updated_at'])
            return success_response(message='该版本已用于收件记录，已作作废处理')
        grant.delete()
        return success_response(message='删除成功')


# ==================== 紧急临时许可 ====================

class EmergencyPermitListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = EmergencyPermit.objects.all().prefetch_related('categories')
        unit_id = request.query_params.get('unit')
        if unit_id:
            queryset = queryset.filter(unit_id=unit_id)
        is_revoked = request.query_params.get('is_revoked')
        if is_revoked in ('true', 'false'):
            queryset = queryset.filter(is_revoked=is_revoked == 'true')
        queryset = queryset.order_by('-valid_from', '-created_at')

        items, total, page, page_size = _paginate(request, queryset)
        return success_response(data={
            'list': EmergencyPermitSerializer(items, many=True).data,
            'total': total, 'page': page, 'page_size': page_size,
        })

    def post(self, request):
        serializer = EmergencyPermitWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))
        data = serializer.validated_data
        permit = EmergencyPermit.objects.create(
            unit=TransferUnit.objects.get(pk=data['unit']),
            reason=data['reason'],
            scope_type=data['scope_type'],
            valid_from=data['valid_from'],
            valid_to=data['valid_to'],
            approved_by=data['approved_by'],
            max_uses=data.get('max_uses'),
            remark=data.get('remark', ''),
            created_by=request.user,
        )
        if data['scope_type'] == AccessGrant.SCOPE_SPECIFIED:
            permit.categories.set(data['categories'])
        logger.info("用户 %s 登记紧急临时许可 #%s", request.user.username, permit.pk)
        return success_response(data=EmergencyPermitSerializer(permit).data, message='创建成功')


class EmergencyPermitRevokeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        permit = EmergencyPermit.objects.filter(pk=pk).first()
        if not permit:
            return error_response(message='紧急临时许可不存在', code=404)
        permit.is_revoked = True
        permit.save(update_fields=['is_revoked'])
        logger.info("用户 %s 撤销紧急临时许可 #%s", request.user.username, permit.pk)
        return success_response(data=EmergencyPermitSerializer(permit).data, message='已撤销')


# ==================== 退回来件批准 ====================

class ReturnApprovalListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = ReturnApproval.objects.all()
        unit_id = request.query_params.get('unit')
        if unit_id:
            queryset = queryset.filter(unit_id=unit_id)
        approval_no = request.query_params.get('approval_no')
        if approval_no:
            queryset = queryset.filter(approval_no__icontains=approval_no)
        queryset = queryset.order_by('-created_at')

        items, total, page, page_size = _paginate(request, queryset)
        return success_response(data={
            'list': ReturnApprovalSerializer(items, many=True).data,
            'total': total, 'page': page, 'page_size': page_size,
        })

    def post(self, request):
        serializer = ReturnApprovalWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(message=_first_error(serializer.errors))
        data = serializer.validated_data
        approval = ReturnApproval.objects.create(
            unit=TransferUnit.objects.get(pk=data['unit']),
            approval_no=data['approval_no'],
            goods_id=data.get('goods'),
            approved_quantity=data['approved_quantity'],
            valid_from=data.get('valid_from'),
            valid_to=data.get('valid_to'),
            remark=data.get('remark', ''),
            created_by=request.user,
        )
        logger.info("用户 %s 登记退回批准 %s", request.user.username, approval.approval_no)
        return success_response(data=ReturnApprovalSerializer(approval).data, message='创建成功')


class ReturnApprovalRevokeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        approval = ReturnApproval.objects.filter(pk=pk).first()
        if not approval:
            return error_response(message='退回批准不存在', code=404)
        approval.is_revoked = True
        approval.save(update_fields=['is_revoked'])
        return success_response(data=ReturnApprovalSerializer(approval).data, message='已撤销')


# ==================== 收件判定与台账 ====================

def _load_receive_context(payload):
    """校验收件入参，返回 (goods, validated_data, error_message)"""
    serializer = ReceiveSerializer(data=payload)
    if not serializer.is_valid():
        return None, None, _first_error(serializer.errors)
    data = serializer.validated_data
    goods = Goods.objects.select_related('variety__category').get(pk=data['goods'])
    return goods, data, None


class AdmissionCheckView(APIView):
    """收件前试判：不落库，返回通过/拒绝的具体依据"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        goods, data, err = _load_receive_context(request.data)
        if err:
            return error_response(message=err)
        decision = evaluate_admission(
            unit_name=data['unit_name'], goods=goods, quantity=data['quantity'],
            kind=data['kind'], at=data.get('received_at'),
            return_approval_no=data.get('return_approval_no', ''),
        )
        return success_response(data={
            'accepted': decision.accepted,
            'kind': decision.kind,
            'unit_id': decision.unit.id if decision.unit else None,
            'unit_name': decision.unit.name if decision.unit else data['unit_name'],
            'goods': goods.id,
            'goods_name': goods.name,
            'category_name': (
                goods.variety.category.name
                if goods.variety and goods.variety.category else ''
            ),
            'quantity': str(data['quantity']),
            'rejection_reason': decision.rejection_reason,
            'basis': decision.basis.as_dict() if decision.basis else None,
            'summary': decision.summary,
        }, message=decision.summary)


class CustodyReceiveView(APIView):
    """正式收件：判定通过入正式台账，拒绝同样留痕（不进入库存台账）"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        goods, data, err = _load_receive_context(request.data)
        if err:
            return error_response(message=err)
        decision, record = receive_transfer(
            unit_name=data['unit_name'], goods=goods, quantity=data['quantity'],
            kind=data['kind'], operator=request.user, at=data.get('received_at'),
            return_approval_no=data.get('return_approval_no', ''),
            batch_no=data.get('batch_no', ''), remark=data.get('remark', ''),
        )
        logger.info(
            "值班员 %s 收件 %s 单位=%s 结论=%s 依据规则=%s",
            request.user.username, data['kind'], data['unit_name'],
            decision.accepted, decision.basis.rule if decision.basis else '-',
        )
        return success_response(
            data={
                'record': CustodyTransferSerializer(record).data,
                'accepted': decision.accepted,
                'basis': decision.basis.as_dict() if decision.basis else None,
                'summary': decision.summary,
            },
            message=decision.summary,
        )


class CustodyTransferListView(APIView):
    """移交/退回台账查询（每条记录均带判定依据）"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = (
            CustodyTransfer.objects
            .select_related('goods__variety__category', 'unit', 'operator', 'grant', 'permit')
            .all()
        )
        params = request.query_params
        if params.get('unit'):
            queryset = queryset.filter(unit_id=params['unit'])
        if params.get('goods'):
            queryset = queryset.filter(goods_id=params['goods'])
        if params.get('category'):
            queryset = queryset.filter(goods__variety__category_id=params['category'])
        if params.get('kind') in (CustodyTransfer.KIND_HANDOVER, CustodyTransfer.KIND_RETURN):
            queryset = queryset.filter(kind=params['kind'])
        if params.get('decision') in (CustodyTransfer.DECISION_ACCEPTED, CustodyTransfer.DECISION_REJECTED):
            queryset = queryset.filter(decision=params['decision'])
        if params.get('unit_name'):
            queryset = queryset.filter(
                Q(unit__name__icontains=params['unit_name'])
                | Q(unit_name_used__icontains=params['unit_name'])
            )
        if params.get('start_date'):
            queryset = queryset.filter(received_at__date__gte=params['start_date'])
        if params.get('end_date'):
            queryset = queryset.filter(received_at__date__lte=params['end_date'])
        queryset = queryset.order_by('-received_at', '-created_at')

        items, total, page, page_size = _paginate(request, queryset)
        return success_response(data={
            'list': CustodyTransferSerializer(items, many=True).data,
            'total': total, 'page': page, 'page_size': page_size,
        })


class CustodyTransferDetailView(APIView):
    """单条收件记录详情（含完整判定依据）"""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        record = (
            CustodyTransfer.objects
            .select_related('goods__variety__category', 'unit', 'operator', 'grant', 'permit')
            .filter(pk=pk).first()
        )
        if not record:
            return error_response(message='收件记录不存在', code=404)
        return success_response(data=CustodyTransferSerializer(record).data)
