"""移交单位准入管理测试"""
from datetime import date
from decimal import Decimal

from rest_framework.test import APIClient

from django.test import TestCase

from apps.authentication.backends import generate_token
from apps.authentication.models import User
from .admission import evaluate_admission
from .models import (
    Authorization, Category, Handover, ReturnApproval, TransferUnit,
    TransferUnitNameRecord, Unit,
)


class AdmissionFixture(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("admission-user", "testpass123", role="admin")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {generate_token(self.user)}")

        # 计量单位与物资品类（既有模型）
        self.measure_unit = Unit.objects.create(name="件", created_by=self.user)
        self.category_a = Category.objects.create(
            name="受控器材", unit=self.measure_unit, created_by=self.user
        )
        self.category_b = Category.objects.create(
            name="封存介质", unit=self.measure_unit, created_by=self.user
        )

        # 外部移交单位
        self.org = TransferUnit.objects.create(
            code="ORG-001", name="东城管理所", created_by=self.user
        )
        TransferUnitNameRecord.objects.create(
            unit=self.org, name="东城管理所", effective_from=date(2025, 1, 1),
            reason="单位建档", created_by=self.user
        )
        self.on_date = date(2026, 10, 3)

    def grant(self, category, kind="regular", valid_from=date(2026, 1, 1),
              valid_to=date(2026, 12, 31), document_no="", unit=None):
        auth = Authorization.objects.create(
            unit=unit or self.org, kind=kind, document_no=document_no,
            valid_from=valid_from, valid_to=valid_to, created_by=self.user,
        )
        auth.categories.add(category)
        return auth


class AdmissionEngineTest(AdmissionFixture):
    def test_regular_authorization_accepted(self):
        self.grant(self.category_a, document_no="常字2026-01")
        decision = evaluate_admission(
            unit_name="东城管理所", category=self.category_a, on_date=self.on_date
        )
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.reason_code, "ok")
        self.assertEqual(decision.name_match_type, "current")
        self.assertIn("适用准入版本", decision.basis_text)

    def test_unknown_unit_rejected(self):
        decision = evaluate_admission(
            unit_name="幽灵单位", category=self.category_a, on_date=self.on_date
        )
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason_code, "unit_not_found")

    def test_expired_authorization_rejected(self):
        self.grant(self.category_a, valid_from=date(2025, 1, 1), valid_to=date(2025, 12, 31))
        decision = evaluate_admission(
            unit_name="东城管理所", category=self.category_a, on_date=self.on_date
        )
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason_code, "not_authorized")
        self.assertIn("不覆盖接收日期", decision.basis_text)

    def test_scope_mismatch_rejected(self):
        # 授权仅覆盖 A，送交 B
        self.grant(self.category_a)
        decision = evaluate_admission(
            unit_name="东城管理所", category=self.category_b, on_date=self.on_date
        )
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason_code, "not_authorized")
        self.assertIn("授权品类范围不包含", decision.basis_text)

    def test_boundary_dates_are_inclusive(self):
        self.grant(self.category_a, valid_from=self.on_date, valid_to=self.on_date)
        decision = evaluate_admission(
            unit_name="东城管理所", category=self.category_a, on_date=self.on_date
        )
        self.assertTrue(decision.accepted)

    def test_suspended_unit_new_handover_rejected_even_with_emergency(self):
        self.grant(self.category_a, kind="emergency", document_no="紧急001")
        self.org.status = "suspended"
        self.org.suspend_reason = "违规调查"
        self.org.save()

        decision = evaluate_admission(
            unit_name="东城管理所", category=self.category_a, on_date=self.on_date
        )
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason_code, "unit_suspended")
        self.assertIsNone(decision.authorization)

    def test_terminated_unit_treated_like_suspended(self):
        self.grant(self.category_a)
        self.org.status = "terminated"
        self.org.save()
        decision = evaluate_admission(
            unit_name="东城管理所", category=self.category_a, on_date=self.on_date
        )
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason_code, "unit_suspended")

    def test_suspended_unit_completes_approved_return(self):
        self.org.status = "suspended"
        self.org.save()
        approval = ReturnApproval.objects.create(
            unit=self.org, document_no="退字2026-09", category=self.category_a,
            quantity=Decimal("2"), approved_by=self.user,
        )
        decision = evaluate_admission(
            unit_name="东城管理所", category=self.category_a, on_date=self.on_date,
            purpose="return", return_document_no="退字2026-09",
        )
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.return_approval, approval)

    def test_suspended_unit_return_without_document_rejected(self):
        self.org.status = "suspended"
        self.org.save()
        decision = evaluate_admission(
            unit_name="东城管理所", category=self.category_a, on_date=self.on_date,
            purpose="return",
        )
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason_code, "return_approval_missing")

    def test_return_category_mismatch_rejected(self):
        ReturnApproval.objects.create(
            unit=self.org, document_no="退字2026-10", category=self.category_a,
            approved_by=self.user,
        )
        decision = evaluate_admission(
            unit_name="东城管理所", category=self.category_b, on_date=self.on_date,
            purpose="return", return_document_no="退字2026-10",
        )
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason_code, "return_approval_mismatch")

    def test_used_return_approval_cannot_reuse(self):
        approval = ReturnApproval.objects.create(
            unit=self.org, document_no="退字2026-11", category=self.category_a,
            approved_by=self.user,
        )
        first = evaluate_admission(
            unit_name="东城管理所", category=self.category_a, on_date=self.on_date,
            purpose="return", return_document_no="退字2026-11",
        )
        self.assertTrue(first.accepted)
        # 模拟首次接收核销
        from .admission import record_handover
        record_handover(decision=first, category=self.category_a, operator=self.user)

        second = evaluate_admission(
            unit_name="东城管理所", category=self.category_a, on_date=self.on_date,
            purpose="return", return_document_no="退字2026-11",
        )
        self.assertFalse(second.accepted)
        self.assertEqual(second.reason_code, "return_approval_unavailable")
        approval.refresh_from_db()
        self.assertEqual(approval.status, "used")

    def test_name_change_resolves_through_history(self):
        # 单位改名：旧名保留为历史名称
        self.org.name = "东城综合保障中心"
        self.org.save()
        TransferUnitNameRecord.objects.create(
            unit=self.org, name="东城综合保障中心",
            effective_from=date(2026, 6, 1), reason="机构改革", created_by=self.user
        )
        self.grant(self.category_a)

        decision = evaluate_admission(
            unit_name="东城管理所", category=self.category_a, on_date=self.on_date
        )
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.unit, self.org)
        self.assertEqual(decision.name_match_type, "alias")
        self.assertIn("历史登记名称", decision.basis_text)

    def test_emergency_permit_outranks_regular(self):
        self.grant(self.category_a, kind="regular", document_no="常规",
                   valid_from=date(2026, 1, 1))
        emergency = self.grant(self.category_a, kind="emergency", document_no="紧急",
                               valid_from=date(2026, 9, 1))
        decision = evaluate_admission(
            unit_name="东城管理所", category=self.category_a, on_date=self.on_date
        )
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.authorization, emergency)
        self.assertEqual(decision.authorization.kind, "emergency")
        self.assertIn("授权重叠", decision.basis_text)

    def test_newer_regular_authorization_wins_on_overlap(self):
        older = self.grant(self.category_a, kind="regular", document_no="旧版",
                           valid_from=date(2026, 1, 1))
        newer = self.grant(self.category_a, kind="regular", document_no="新版",
                           valid_from=date(2026, 7, 1))
        decision = evaluate_admission(
            unit_name="东城管理所", category=self.category_a, on_date=self.on_date
        )
        self.assertEqual(decision.authorization, newer)
        self.assertNotEqual(older, newer)

    def test_revoked_authorization_ignored(self):
        revoked = self.grant(self.category_a, document_no="已撤销")
        revoked.revoked_at = revoked.created_at
        revoked.save()
        decision = evaluate_admission(
            unit_name="东城管理所", category=self.category_a, on_date=self.on_date
        )
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason_code, "not_authorized")


class AdmissionAPITest(AdmissionFixture):
    def _create_unit(self, code, name):
        resp = self.client.post("/api/transfer-units/", {"code": code, "name": name}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.json()["data"]

    def test_create_unit_and_duplicate_name_rejected(self):
        ok = self.client.post(
            "/api/transfer-units/", {"code": "ORG-002", "name": "西站管委会"}, format="json"
        )
        dup = self.client.post(
            "/api/transfer-units/", {"code": "ORG-003", "name": "西站管委会"}, format="json"
        )
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(dup.status_code, 400)

    def test_rename_blocks_collision_with_other_unit_history(self):
        other = self._create_unit("ORG-002", "西站管委会")
        # 本单位改名
        resp = self.client.post(
            f"/api/transfer-units/{self.org.id}/rename/",
            {"new_name": "东城综合保障中心", "effective_from": "2026-06-01"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        # 其他单位不得改用已登记名称（当前名或历史名）
        collision = self.client.post(
            f"/api/transfer-units/{other['id']}/rename/",
            {"new_name": "东城管理所", "effective_from": "2026-07-01"},
            format="json",
        )
        self.assertEqual(collision.status_code, 400)

    def test_authorization_crud_and_revoke(self):
        created = self.client.post("/api/authorizations/", {
            "unit": self.org.id, "kind": "regular",
            "category_ids": [self.category_a.id],
            "valid_from": "2026-01-01", "valid_to": "2026-12-31",
            "document_no": "常字2026-01",
        }, format="json")
        self.assertEqual(created.status_code, 200, created.content)
        auth_id = created.json()["data"]["id"]

        listing = self.client.get(f"/api/authorizations/?unit={self.org.id}")
        self.assertEqual(listing.json()["data"]["total"], 1)

        revoked = self.client.post(
            f"/api/authorizations/{auth_id}/revoke/", {"reason": "年度换发"}, format="json"
        )
        self.assertEqual(revoked.status_code, 200)
        self.assertTrue(revoked.json()["data"]["is_revoked"])

    def test_authorization_validates_range_and_scope(self):
        bad_range = self.client.post("/api/authorizations/", {
            "unit": self.org.id, "category_ids": [self.category_a.id],
            "valid_from": "2026-12-31", "valid_to": "2026-01-01",
        }, format="json")
        bad_category = self.client.post("/api/authorizations/", {
            "unit": self.org.id, "category_ids": [99999],
            "valid_from": "2026-01-01", "valid_to": "2026-12-31",
        }, format="json")
        empty_scope = self.client.post("/api/authorizations/", {
            "unit": self.org.id, "category_ids": [],
            "valid_from": "2026-01-01", "valid_to": "2026-12-31",
        }, format="json")
        self.assertEqual(bad_range.status_code, 400)
        self.assertEqual(bad_category.status_code, 400)
        self.assertEqual(empty_scope.status_code, 400)

    def test_evaluate_does_not_write_ledger(self):
        self.grant(self.category_a)
        resp = self.client.post("/api/admission/evaluate/", {
            "unit_name": "东城管理所", "category": self.category_a.id,
            "on_date": "2026-10-03",
        }, format="json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertTrue(data["accepted"])
        self.assertTrue(data["basis"])
        self.assertEqual(Handover.objects.count(), 0)

    def test_receive_accepted_writes_ledger_with_basis(self):
        auth = self.grant(self.category_a, document_no="常字2026-01")
        resp = self.client.post("/api/handovers/receive/", {
            "unit_name": "东城管理所", "category": self.category_a.id,
            "material_name": "执法记录仪", "quantity": "5",
            "on_date": "2026-10-03",
        }, format="json")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["success"])
        self.assertEqual(Handover.objects.count(), 1)
        handover = Handover.objects.get()
        self.assertEqual(handover.decision, "accepted")
        self.assertEqual(handover.authorization, auth)
        self.assertIn("适用准入版本", handover.basis)

        detail = self.client.get(f"/api/handovers/{handover.id}/")
        self.assertEqual(detail.status_code, 200)
        self.assertTrue(detail.json()["data"]["basis_lines"])

    def test_receive_rejected_also_recorded_and_explained(self):
        # 无任何授权
        resp = self.client.post("/api/handovers/receive/", {
            "unit_name": "东城管理所", "category": self.category_a.id,
            "on_date": "2026-10-03",
        }, format="json")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["success"])
        self.assertIn("接收拒绝", body["message"])
        handover = Handover.objects.get()
        self.assertEqual(handover.decision, "rejected")
        self.assertTrue(handover.reject_reason)
        self.assertIn("无任一适用版本", handover.basis)
        self.assertIn("结论为拒绝", handover.basis)

    def test_suspended_unit_return_flow_consumes_approval(self):
        self.client.post(
            f"/api/transfer-units/{self.org.id}/status/",
            {"status": "suspended", "reason": "调查"}, format="json",
        )
        # 新移交被拒
        blocked = self.client.post("/api/handovers/receive/", {
            "unit_name": "东城管理所", "category": self.category_a.id,
            "on_date": "2026-10-03",
        }, format="json")
        self.assertFalse(blocked.json()["success"])

        # 登记退回批准单并完成退回
        approval_resp = self.client.post("/api/return-approvals/", {
            "unit": self.org.id, "document_no": "退字2026-09",
            "category": self.category_a.id, "quantity": "1",
        }, format="json")
        self.assertEqual(approval_resp.status_code, 200, approval_resp.content)

        returned = self.client.post("/api/handovers/receive/", {
            "unit_name": "东城管理所", "category": self.category_a.id,
            "purpose": "return", "return_document_no": "退字2026-09",
            "on_date": "2026-10-03",
        }, format="json")
        self.assertTrue(returned.json()["success"], returned.content)
        self.assertEqual(ReturnApproval.objects.get().status, "used")

    def test_handover_list_filters(self):
        self.grant(self.category_a)
        self.client.post("/api/handovers/receive/", {
            "unit_name": "东城管理所", "category": self.category_a.id,
            "on_date": "2026-10-03",
        }, format="json")
        self.client.post("/api/handovers/receive/", {
            "unit_name": "东城管理所", "category": self.category_b.id,
            "on_date": "2026-10-03",
        }, format="json")

        accepted = self.client.get("/api/handovers/?decision=accepted")
        rejected = self.client.get("/api/handovers/?decision=rejected")
        self.assertEqual(accepted.json()["data"]["total"], 1)
        self.assertEqual(rejected.json()["data"]["total"], 1)

        by_unit = self.client.get("/api/handovers/?unit_name=东城")
        self.assertEqual(by_unit.json()["data"]["total"], 2)

    def test_admission_requires_authentication(self):
        resp = APIClient().post("/api/admission/evaluate/", {
            "unit_name": "东城管理所", "category": self.category_a.id,
        }, format="json")
        self.assertEqual(resp.status_code, 401)
