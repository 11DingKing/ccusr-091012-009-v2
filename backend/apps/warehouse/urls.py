"""
仓库管理URL配置
"""
from django.urls import path
from .views import (
    UnitListView, UnitDetailView, UnitBatchDeleteView, UnitAllView,
    CategoryListView, CategoryDetailView, CategoryBatchDeleteView, CategoryAllView,
    VarietyListView, VarietyDetailView, VarietyBatchDeleteView,
    VarietyTemplateView, VarietyImportView,
    DashboardView, GoodsListView, StockInListView, StockOutListView,
    WarningListView, ApprovalListView
)
from .access_views import (
    TransferUnitListView, TransferUnitAllView, TransferUnitDetailView,
    TransferUnitSuspendView, TransferUnitResumeView, UnitNameChangeListView,
    AccessGrantListView, AccessGrantDetailView,
    EmergencyPermitListView, EmergencyPermitRevokeView,
    ReturnApprovalListView, ReturnApprovalRevokeView,
    AdmissionCheckView, CustodyReceiveView,
    CustodyTransferListView, CustodyTransferDetailView,
)

urlpatterns = [
    # 仪表盘
    path('dashboard/', DashboardView.as_view(), name='dashboard'),

    # 单位管理
    path('units/', UnitListView.as_view(), name='unit-list'),
    path('units/all/', UnitAllView.as_view(), name='unit-all'),
    path('units/batch-delete/', UnitBatchDeleteView.as_view(), name='unit-batch-delete'),
    path('units/<int:pk>/', UnitDetailView.as_view(), name='unit-detail'),

    # 品类管理
    path('categories/', CategoryListView.as_view(), name='category-list'),
    path('categories/all/', CategoryAllView.as_view(), name='category-all'),
    path('categories/batch-delete/', CategoryBatchDeleteView.as_view(), name='category-batch-delete'),
    path('categories/<int:pk>/', CategoryDetailView.as_view(), name='category-detail'),

    # 品种管理
    path('varieties/', VarietyListView.as_view(), name='variety-list'),
    path('varieties/batch-delete/', VarietyBatchDeleteView.as_view(), name='variety-batch-delete'),
    path('varieties/template/', VarietyTemplateView.as_view(), name='variety-template'),
    path('varieties/import/', VarietyImportView.as_view(), name='variety-import'),
    path('varieties/<int:pk>/', VarietyDetailView.as_view(), name='variety-detail'),

    # 货物管理
    path('goods/', GoodsListView.as_view(), name='goods-list'),

    # 入库管理
    path('stock-in/', StockInListView.as_view(), name='stock-in-list'),

    # 出库管理
    path('stock-out/', StockOutListView.as_view(), name='stock-out-list'),

    # 预警管理
    path('warnings/', WarningListView.as_view(), name='warning-list'),

    # 审批管理
    path('approvals/', ApprovalListView.as_view(), name='approval-list'),

    # ==================== 移交单位准入管理 ====================
    path('transfer-units/', TransferUnitListView.as_view(), name='transfer-unit-list'),
    path('transfer-units/all/', TransferUnitAllView.as_view(), name='transfer-unit-all'),
    path('transfer-units/<int:pk>/', TransferUnitDetailView.as_view(), name='transfer-unit-detail'),
    path('transfer-units/<int:pk>/suspend/', TransferUnitSuspendView.as_view(), name='transfer-unit-suspend'),
    path('transfer-units/<int:pk>/resume/', TransferUnitResumeView.as_view(), name='transfer-unit-resume'),
    path('transfer-units/<int:pk>/name-changes/', UnitNameChangeListView.as_view(), name='unit-name-change-list'),

    path('access-grants/', AccessGrantListView.as_view(), name='access-grant-list'),
    path('access-grants/<int:pk>/', AccessGrantDetailView.as_view(), name='access-grant-detail'),

    path('emergency-permits/', EmergencyPermitListView.as_view(), name='emergency-permit-list'),
    path('emergency-permits/<int:pk>/revoke/', EmergencyPermitRevokeView.as_view(), name='emergency-permit-revoke'),

    path('return-approvals/', ReturnApprovalListView.as_view(), name='return-approval-list'),
    path('return-approvals/<int:pk>/revoke/', ReturnApprovalRevokeView.as_view(), name='return-approval-revoke'),

    # 收件准入：试判、正式收件、台账查询
    path('custody/check/', AdmissionCheckView.as_view(), name='custody-admission-check'),
    path('custody/receive/', CustodyReceiveView.as_view(), name='custody-receive'),
    path('custody/transfers/', CustodyTransferListView.as_view(), name='custody-transfer-list'),
    path('custody/transfers/<int:pk>/', CustodyTransferDetailView.as_view(), name='custody-transfer-detail'),
]
