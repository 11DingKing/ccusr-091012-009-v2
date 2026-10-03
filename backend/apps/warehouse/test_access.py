"""
移交单位准入管理测试

覆盖：
- 授权范围与有效期版本选择（物资类型 + 日期）
- 暂停单位仅能完成已批准退回、不能发起新移交
- 名称变更链的主体解析
- 授权重叠的版本优先级
- 紧急临时许可的优先级（窗口内覆盖常规授权，窗口外失效）
- 查询结果说明每次通过/拒绝的具体依据
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.authentication.backends import generate_token
from apps.authentication.models import User
from .models import Category, Goods, Unit, Variety
from .access_models import (
    AccessGrant, CustodyTransfer, EmergencyPermit, ReturnApproval,
    TransferUnit, UnitNameChange,
)
from .access_control import evaluate_admission, receive_transfer, resolve_unit


class AdmissionFixture(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("duty-officer", "testpass123", role="admin")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {generate_token(self.user)}")

        # 两个物资类型（品类）
        self.unit_dim = Unit.objects.create(name="件", created_by=self.user)
        self.cat_device = Category.objects.create(name="受控器材", unit=self.unit_dim, created_by=self.user)
        self.cat_media = Category.objects.create(name="封存介质", unit=self.unit_dim, created_by=self.user)
        self.var_device = Variety.objects.create(name="记录终端", category=self.cat_device, created_by=self.user)
        self.var_media = Variety.objects.create(name="封存硬盘", category=self.cat_media, created_by=self.user)
        self.goods_device = Goods.objects.create(
            variety=self.var_device, name="执法记录终端", code="DEV-001", quantity=Decimal("0")
        )
        self.goods_media = Goods.objects.create(
            variety=self.var_media, name="500G封存硬盘", code="MED-001", quantity=Decimal("0")
        )

        # 外部移交单位
        self.org = TransferUnit.objects.create(name="东城分局", created_by=self.user)
        self.now = timezone.now()

    def grant(self, unit=None, scope=AccessGrant.SCOPE_SPECIFIED, categories=None,
              start=None, end=None, version='', active=True):
        g = AccessGrant.objects.create(
            unit=unit or self.org, scope_type=scope,
            effective_from=start, effective_to=end,
            version_no=version, is_active=active, created_by=self.user,
        )
        if scope == AccessGrant.SCOPE_SPECIFIED:
            g.categories.set(categories or [self.cat_device])
        return g


class NameChangeTest(AdmissionFixture):
    def test_resolve_current_and_previous_name(self):
        self.org.name = "东城公安分局"
        self.org.save()
        UnitNameChange.objects.create(
            unit=self.org, previous_name="东城分局", current_name="东城公安分局",
            created_by=self.user,
        )
        unit, alias = resolve_unit("东城公安分局")
        self.assertEqual(unit, self.org)
        self.assertFalse(alias)
        unit, alias = resolve_unit("东城分局")
        self.assertEqual(unit, self.org)
        self.assertTrue(alias)

    def test_resolve_unknown_name(self):
        unit, alias = resolve_unit("不存在单位")
        self.assertIsNone(unit)
        self.assertEqual(alias, '')

    def test_api_rename_registers_change_chain(self):
        resp = self.client.put(f"/api/transfer-units/{self.org.id}/", {"name": "东城公安分局"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.org.refresh_from_db()
        self.assertEqual(self.org.name, "东城公安分局")
        self.assertTrue(self.org.name_changes.filter(previous_name="东城分局").exists())


class GrantVersionTest(AdmissionFixture):
    def test_grant_in_scope_within_validity_accepted(self):
        self.grant(categories=[self.cat_device], start=self.now - timedelta(days=30),
                   end=self.now + timedelta(days=30), version='2026-A')
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("2"),
            kind='handover',
        )
        self.assertTrue(d.accepted)
        self.assertEqual(d.basis.rule, 'P2')
        self.assertIn('2026-A', d.basis.detail)
        self.assertIn('受控器材', d.basis.detail)

    def test_out_of_scope_rejected_with_basis(self):
        # 授权仅覆盖封存介质，送交受控器材
        self.grant(categories=[self.cat_media], start=self.now - timedelta(days=1),
                   end=self.now + timedelta(days=30), version='MED-ONLY')
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("1"), kind='handover',
        )
        self.assertFalse(d.accepted)
        self.assertEqual(d.rejection_reason, '授权范围不符')
        self.assertIn('受控器材', d.basis.detail)
        self.assertIn('不覆盖', d.basis.detail)

    def test_expired_grant_rejected(self):
        self.grant(categories=[self.cat_device], start=self.now - timedelta(days=60),
                   end=self.now - timedelta(days=1), version='OLD')
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("1"), kind='handover',
        )
        self.assertFalse(d.accepted)
        self.assertEqual(d.rejection_reason, '授权已过期')
        self.assertIn('OLD', d.basis.detail)

    def test_future_grant_rejected(self):
        self.grant(categories=[self.cat_device], start=self.now + timedelta(days=5),
                   end=self.now + timedelta(days=30))
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("1"), kind='handover',
        )
        self.assertFalse(d.accepted)
        self.assertEqual(d.rejection_reason, '授权尚未生效')

    def test_no_grant_rejected(self):
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("1"), kind='handover',
        )
        self.assertFalse(d.accepted)
        self.assertEqual(d.rejection_reason, '单位无准入授权')

    def test_overlapping_grants_latest_effective_version_wins(self):
        """授权重叠：同一品类存在两个交叠版本，取生效日期最新者"""
        old = self.grant(categories=[self.cat_device], start=self.now - timedelta(days=60),
                         end=self.now + timedelta(days=10), version='V1')
        new = self.grant(categories=[self.cat_device], start=self.now - timedelta(days=5),
                         end=self.now + timedelta(days=30), version='V2')
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("1"), kind='handover',
        )
        self.assertTrue(d.accepted)
        self.assertEqual(d.basis.grant_id, new.id)
        self.assertNotEqual(d.basis.grant_id, old.id)

    def test_receive_at_date_selects_version_effective_on_that_date(self):
        """按收件日期选择当时适用的版本：旧版本在当年1月有效，新版本3月才生效"""
        old = self.grant(categories=[self.cat_device], start=self.now - timedelta(days=400),
                         end=self.now - timedelta(days=200), version='PAST-V')
        self.grant(categories=[self.cat_device], start=self.now - timedelta(days=10),
                   end=self.now + timedelta(days=30), version='CURRENT-V')
        past_date = self.now - timedelta(days=300)
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("1"),
            kind='handover', at=past_date,
        )
        self.assertTrue(d.accepted)
        self.assertEqual(d.basis.grant_id, old.id)

    def test_scope_all_covers_any_category(self):
        self.grant(scope=AccessGrant.SCOPE_ALL, start=self.now - timedelta(days=1),
                   end=self.now + timedelta(days=10), version='ALL')
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_media, quantity=Decimal("1"), kind='handover',
        )
        self.assertTrue(d.accepted)


class EmergencyPermitTest(AdmissionFixture):
    def _permit(self, categories=None, start=None, end=None, revoked=False, max_uses=None):
        p = EmergencyPermit.objects.create(
            unit=self.org, reason='专案紧急收件', scope_type=AccessGrant.SCOPE_SPECIFIED,
            valid_from=start or self.now - timedelta(hours=1),
            valid_to=end or self.now + timedelta(hours=2),
            approved_by='值班领导', is_revoked=revoked, max_uses=max_uses,
            created_by=self.user,
        )
        p.categories.set(categories or [self.cat_device])
        return p

    def test_permit_overrides_missing_grant(self):
        """无常规授权时，窗口内紧急许可放行，且依据中标注 P1 优先"""
        self._permit()
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("1"), kind='handover',
        )
        self.assertTrue(d.accepted)
        self.assertEqual(d.basis.rule, 'P1')
        self.assertIn('紧急临时许可', d.basis.detail)
        self.assertIn('P1', d.basis.detail)

    def test_permit_takes_priority_over_valid_grant(self):
        """紧急许可与常规授权同时有效：P1 胜出，依据中同时保留常规授权版本"""
        grant = self.grant(categories=[self.cat_device], start=self.now - timedelta(days=1),
                           end=self.now + timedelta(days=10), version='NORMAL')
        permit = self._permit()
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("1"), kind='handover',
        )
        self.assertTrue(d.accepted)
        self.assertEqual(d.basis.rule, 'P1')
        self.assertEqual(d.basis.permit_id, permit.id)
        self.assertEqual(d.basis.grant_id, grant.id)

    def test_permit_overrides_scope_mismatch(self):
        """常规授权范围不符，但紧急许可覆盖该品类时放行"""
        self.grant(categories=[self.cat_media], start=self.now - timedelta(days=1),
                   end=self.now + timedelta(days=10))
        self._permit()
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("1"), kind='handover',
        )
        self.assertTrue(d.accepted)
        self.assertEqual(d.basis.rule, 'P1')

    def test_expired_permit_does_not_apply(self):
        self._permit(end=self.now - timedelta(minutes=1))
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("1"), kind='handover',
        )
        self.assertFalse(d.accepted)
        self.assertIn('授权', d.rejection_reason)

    def test_permit_not_started(self):
        self._permit(start=self.now + timedelta(hours=1))
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("1"), kind='handover',
        )
        self.assertFalse(d.accepted)

    def test_permit_scope_mismatch_still_rejected(self):
        self._permit(categories=[self.cat_media])
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("1"), kind='handover',
        )
        self.assertFalse(d.accepted)

    def test_revoked_permit_rejected(self):
        self._permit(revoked=True)
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("1"), kind='handover',
        )
        self.assertFalse(d.accepted)

    def test_permit_max_uses_enforced(self):
        p = self._permit(max_uses=1)
        receive_transfer(unit_name="东城分局", goods=self.goods_device, quantity=Decimal("1"),
                         kind='handover', operator=self.user)
        p.refresh_from_db()
        self.assertEqual(p.used_count, 1)
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("1"), kind='handover',
        )
        self.assertFalse(d.accepted)


class SuspensionTest(AdmissionFixture):
    def setUp(self):
        super().setUp()
        self.grant(categories=[self.cat_device], start=self.now - timedelta(days=1),
                   end=self.now + timedelta(days=30), version='ACTIVE')
        self.org.suspend(reason='资质复核')

    def test_suspended_unit_new_handover_rejected(self):
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("1"), kind='handover',
        )
        self.assertFalse(d.accepted)
        self.assertEqual(d.basis.rule, 'P0')
        self.assertEqual(d.rejection_reason, '单位已暂停合作，不能发起新移交')
        self.assertIn('只能完成已批准的退回', d.basis.detail)

    def test_emergency_permit_cannot_override_suspension(self):
        """P0 暂停优先级高于 P1 紧急许可：暂停单位持紧急许可也不能新移交"""
        EmergencyPermit.objects.create(
            unit=self.org, reason='紧急', scope_type=AccessGrant.SCOPE_ALL,
            valid_from=self.now - timedelta(hours=1), valid_to=self.now + timedelta(hours=2),
            approved_by='领导', created_by=self.user,
        )
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("1"), kind='handover',
        )
        self.assertFalse(d.accepted)
        self.assertEqual(d.basis.rule, 'P0')
        self.assertIn('P0', d.basis.detail)

    def test_suspended_unit_return_with_valid_approval_accepted(self):
        approval = ReturnApproval.objects.create(
            unit=self.org, goods=self.goods_device, approval_no='RT-2026-01',
            approved_quantity=Decimal("5"),
            valid_from=self.now - timedelta(days=1), valid_to=self.now + timedelta(days=5),
            created_by=self.user,
        )
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("2"),
            kind='return', return_approval_no='RT-2026-01',
        )
        self.assertTrue(d.accepted)
        self.assertEqual(d.basis.rule, 'P0')
        self.assertEqual(d.basis.return_approval_id, approval.id)

    def test_suspended_unit_return_without_approval_rejected(self):
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("1"),
            kind='return', return_approval_no='',
        )
        self.assertFalse(d.accepted)
        self.assertIn('批准文号', d.basis.detail)

    def test_return_approval_over_quantity_rejected(self):
        ReturnApproval.objects.create(
            unit=self.org, goods=self.goods_device, approval_no='RT-2',
            approved_quantity=Decimal("3"),
            valid_from=self.now - timedelta(days=1), valid_to=self.now + timedelta(days=5),
            created_by=self.user,
        )
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("4"),
            kind='return', return_approval_no='RT-2',
        )
        self.assertFalse(d.accepted)
        self.assertIn('剩余可退数量', d.basis.detail)

    def test_return_approval_expired_rejected(self):
        ReturnApproval.objects.create(
            unit=self.org, goods=self.goods_device, approval_no='RT-3',
            approved_quantity=Decimal("3"),
            valid_from=self.now - timedelta(days=10), valid_to=self.now - timedelta(days=1),
            created_by=self.user,
        )
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("1"),
            kind='return', return_approval_no='RT-3',
        )
        self.assertFalse(d.accepted)
        self.assertIn('不在有效期', d.basis.detail)

    def test_return_approval_wrong_goods_rejected(self):
        ReturnApproval.objects.create(
            unit=self.org, goods=self.goods_media, approval_no='RT-4',
            approved_quantity=Decimal("3"),
            valid_from=self.now - timedelta(days=1), valid_to=self.now + timedelta(days=5),
            created_by=self.user,
        )
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("1"),
            kind='return', return_approval_no='RT-4',
        )
        self.assertFalse(d.accepted)
        self.assertIn('物资与本次来件不符', d.basis.detail)

    def test_completed_return_consumes_approval_quantity(self):
        approval = ReturnApproval.objects.create(
            unit=self.org, goods=self.goods_device, approval_no='RT-5',
            approved_quantity=Decimal("3"),
            valid_from=self.now - timedelta(days=1), valid_to=self.now + timedelta(days=5),
            created_by=self.user,
        )
        receive_transfer(unit_name="东城分局", goods=self.goods_device, quantity=Decimal("2"),
                         kind='return', return_approval_no='RT-5', operator=self.user)
        approval.refresh_from_db()
        self.assertEqual(approval.used_quantity, Decimal("2"))
        self.assertEqual(approval.remaining_quantity, Decimal("1"))
        # 再退 2 件超出剩余额度
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("2"),
            kind='return', return_approval_no='RT-5',
        )
        self.assertFalse(d.accepted)

    def test_resume_restores_handover(self):
        self.org.resume()
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("1"), kind='handover',
        )
        self.assertTrue(d.accepted)


class ActiveUnitReturnTest(AdmissionFixture):
    """正常合作单位的退回同样必须持退回批准；与暂停状态无关"""

    def test_active_unit_return_requires_approval(self):
        self.grant(categories=[self.cat_device], start=self.now - timedelta(days=1),
                   end=self.now + timedelta(days=10), version='V')
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("1"),
            kind='return', return_approval_no='',
        )
        self.assertFalse(d.accepted)
        self.assertIn('批准文号', d.basis.detail)

    def test_active_unit_return_with_approval_accepted(self):
        self.grant(categories=[self.cat_device], start=self.now - timedelta(days=1),
                   end=self.now + timedelta(days=10), version='V')
        ReturnApproval.objects.create(
            unit=self.org, goods=self.goods_device, approval_no='RT-A',
            approved_quantity=Decimal("2"),
            valid_from=self.now - timedelta(days=1), valid_to=self.now + timedelta(days=5),
            created_by=self.user,
        )
        d = evaluate_admission(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("1"),
            kind='return', return_approval_no='RT-A',
        )
        self.assertTrue(d.accepted)
        self.assertEqual(d.basis.return_approval_id, ReturnApproval.objects.get(approval_no='RT-A').id)


class ReceiveLedgerTest(AdmissionFixture):
    def test_accepted_receive_creates_ledger_with_basis(self):
        self.grant(categories=[self.cat_device], start=self.now - timedelta(days=1),
                   end=self.now + timedelta(days=10), version='V1')
        decision, record = receive_transfer(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("2"),
            kind='handover', operator=self.user, batch_no='B001',
        )
        self.assertTrue(decision.accepted)
        self.assertEqual(record.decision, CustodyTransfer.DECISION_ACCEPTED)
        self.assertEqual(record.basis_type, CustodyTransfer.BASIS_GRANT)
        self.assertTrue(record.decision_basis)
        self.assertEqual(CustodyTransfer.objects.count(), 1)

    def test_rejected_receive_also_recorded_but_marked(self):
        decision, record = receive_transfer(
            unit_name="东城分局", goods=self.goods_device, quantity=Decimal("1"),
            kind='handover', operator=self.user,
        )
        self.assertFalse(decision.accepted)
        self.assertEqual(record.decision, CustodyTransfer.DECISION_REJECTED)
        self.assertTrue(record.rejection_reason)
        self.assertTrue(record.decision_basis)

    def test_unknown_unit_record_persists_rejection(self):
        decision, record = receive_transfer(
            unit_name="幽灵单位", goods=self.goods_device, quantity=Decimal("1"),
            kind='handover', operator=self.user,
        )
        self.assertFalse(decision.accepted)
        self.assertIsNone(record.unit)
        self.assertEqual(record.unit_name_used, "幽灵单位")

    def test_alias_name_resolution_recorded_in_basis(self):
        UnitNameChange.objects.create(
            unit=self.org, previous_name="东城分局旧称", current_name=self.org.name,
            created_by=self.user,
        )
        self.grant(categories=[self.cat_device], start=self.now - timedelta(days=1),
                   end=self.now + timedelta(days=10), version='V1')
        d = evaluate_admission(
            unit_name="东城分局旧称", goods=self.goods_device, quantity=Decimal("1"),
            kind='handover',
        )
        self.assertTrue(d.accepted)
        self.assertTrue(d.basis.unit_resolved_via_alias)
        self.assertEqual(d.basis.previous_name, "东城分局旧称")
        self.assertIn('名称变更链', d.basis.detail)


class AdmissionAPITest(AdmissionFixture):
    def _make_grant(self):
        return self.grant(categories=[self.cat_device], start=self.now - timedelta(days=1),
                          end=self.now + timedelta(days=10), version='API-V')

    def test_check_endpoint_returns_basis(self):
        self._make_grant()
        resp = self.client.post('/api/custody/check/', {
            'unit_name': '东城分局', 'goods': self.goods_device.id, 'quantity': '3',
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()['data']
        self.assertTrue(body['accepted'])
        self.assertEqual(body['basis']['rule'], 'P2')
        self.assertIn('API-V', body['summary'])

    def test_check_rejects_scope_mismatch(self):
        resp = self.client.post('/api/custody/check/', {
            'unit_name': '东城分局', 'goods': self.goods_device.id, 'quantity': '1',
        }, format='json')
        body = resp.json()['data']
        self.assertFalse(body['accepted'])
        self.assertTrue(body['basis']['detail'])

    def test_receive_endpoint_persists_and_returns_basis(self):
        self._make_grant()
        resp = self.client.post('/api/custody/receive/', {
            'unit_name': '东城分局', 'goods': self.goods_device.id,
            'quantity': '2', 'batch_no': 'BX',
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()['data']
        self.assertTrue(body['accepted'])
        self.assertEqual(body['record']['decision_basis'][:1] != '', True)

    def test_suspended_unit_receive_flow_via_api(self):
        self._make_grant()
        # 暂停
        rsp = self.client.post(f'/api/transfer-units/{self.org.id}/suspend/',
                               {'suspend_reason': '复核'}, format='json')
        self.assertEqual(rsp.status_code, 200)
        # 新移交被拒
        denied = self.client.post('/api/custody/receive/', {
            'unit_name': '东城分局', 'goods': self.goods_device.id, 'quantity': '1',
        }, format='json')
        self.assertFalse(denied.json()['data']['accepted'])
        # 登记退回批准
        ra = self.client.post('/api/return-approvals/', {
            'unit': self.org.id, 'approval_no': 'RA-1', 'goods': self.goods_device.id,
            'approved_quantity': '2',
        }, format='json')
        self.assertEqual(ra.status_code, 200)
        # 退回通过
        accepted = self.client.post('/api/custody/receive/', {
            'unit_name': '东城分局', 'goods': self.goods_device.id, 'quantity': '2',
            'kind': 'return', 'return_approval_no': 'RA-1',
        }, format='json')
        self.assertTrue(accepted.json()['data']['accepted'])
        self.assertEqual(accepted.json()['data']['record']['basis_type'], 'return_approval')

    def test_return_requires_approval_no(self):
        resp = self.client.post('/api/custody/check/', {
            'unit_name': '东城分局', 'goods': self.goods_device.id,
            'quantity': '1', 'kind': 'return',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('批准文号', resp.json()['message'])

    def test_transfer_list_filters_and_shows_basis(self):
        self._make_grant()
        self.client.post('/api/custody/receive/', {
            'unit_name': '东城分局', 'goods': self.goods_device.id, 'quantity': '2',
        }, format='json')
        # 仅查通过
        resp = self.client.get('/api/custody/transfers/?decision=accepted')
        self.assertEqual(resp.json()['data']['total'], 1)
        row = resp.json()['data']['list'][0]
        self.assertTrue(row['decision_basis'])
        self.assertEqual(row['basis_type'], 'grant')
        # 按单位过滤
        resp2 = self.client.get(f'/api/custody/transfers/?unit={self.org.id}')
        self.assertEqual(resp2.json()['data']['total'], 1)

    def test_requires_authentication(self):
        anon = APIClient().post('/api/custody/check/', {}, format='json')
        self.assertEqual(anon.status_code, 401)


class EmergencyPermitApiTest(AdmissionFixture):
    def test_create_permit_and_revoke(self):
        resp = self.client.post('/api/emergency-permits/', {
            'unit': self.org.id, 'reason': '专案',
            'categories': [self.cat_device.id],
            'valid_from': (self.now - timedelta(hours=1)).isoformat(),
            'valid_to': (self.now + timedelta(hours=2)).isoformat(),
            'approved_by': '领导', 'max_uses': 1,
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        pid = resp.json()['data']['id']
        revoke = self.client.post(f'/api/emergency-permits/{pid}/revoke/', {}, format='json')
        self.assertEqual(revoke.status_code, 200)
        check = self.client.post('/api/custody/check/', {
            'unit_name': '东城分局', 'goods': self.goods_device.id, 'quantity': '1',
        }, format='json')
        self.assertFalse(check.json()['data']['accepted'])

    def test_specified_scope_requires_categories(self):
        resp = self.client.post('/api/access-grants/', {
            'unit': self.org.id, 'scope_type': 'specified', 'categories': [],
        }, format='json')
        self.assertEqual(resp.status_code, 400)
