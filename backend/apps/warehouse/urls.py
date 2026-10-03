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
    WarningListView, ApprovalListView,
    TransferUnitListView, TransferUnitDetailView, TransferUnitRenameView,
    TransferUnitStatusView,
    AuthorizationListView, AuthorizationDetailView, AuthorizationRevokeView,
    ReturnApprovalListView,
    AdmissionEvaluateView, HandoverReceiveView, HandoverListView, HandoverDetailView,
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

    # 移交单位准入管理
    path('transfer-units/', TransferUnitListView.as_view(), name='transfer-unit-list'),
    path('transfer-units/<int:pk>/', TransferUnitDetailView.as_view(), name='transfer-unit-detail'),
    path('transfer-units/<int:pk>/rename/', TransferUnitRenameView.as_view(), name='transfer-unit-rename'),
    path('transfer-units/<int:pk>/status/', TransferUnitStatusView.as_view(), name='transfer-unit-status'),

    # 准入授权
    path('authorizations/', AuthorizationListView.as_view(), name='authorization-list'),
    path('authorizations/<int:pk>/', AuthorizationDetailView.as_view(), name='authorization-detail'),
    path('authorizations/<int:pk>/revoke/', AuthorizationRevokeView.as_view(), name='authorization-revoke'),

    # 退回批准单
    path('return-approvals/', ReturnApprovalListView.as_view(), name='return-approval-list'),

    # 收件准入判定与接收台账
    path('admission/evaluate/', AdmissionEvaluateView.as_view(), name='admission-evaluate'),
    path('handovers/', HandoverListView.as_view(), name='handover-list'),
    path('handovers/receive/', HandoverReceiveView.as_view(), name='handover-receive'),
    path('handovers/<int:pk>/', HandoverDetailView.as_view(), name='handover-detail'),
]
