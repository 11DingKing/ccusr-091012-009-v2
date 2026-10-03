# 监管物资保管服务

该项目为监管仓、证物室和受控物资保管点提供服务端 API，覆盖人员授权、物资分类、批次登记、收发记录、审批、预警、审计日志与统计报表。数据保存在 SQLite，所有测试和接口验收均可在单个 Linux 应用容器内离线完成。

## 运行环境

- Python 3.11
- Django REST Framework
- SQLite

## 安装与初始化

```bash
python -m pip install -r backend/requirements.txt
cd backend
python manage.py migrate --run-syncdb
```

## 测试

```bash
cd backend
pytest -q
```

## 编译检查

```bash
python -m compileall -q backend
```

## API 验收

```bash
cd backend
python manage.py migrate --run-syncdb
python manage.py shell -c "from rest_framework.test import APIClient; from apps.authentication.models import User; u=User.objects.create_user('smoke','safe-pass',role='admin'); c=APIClient(); r=c.post('/api/auth/login/',{'username':'smoke','password':'safe-pass'},format='json'); print(r.status_code, bool(r.json()['data']['token']))"
```

## 容器

```bash
docker build -t custody-service .
docker run --rm custody-service
```

## 移交单位准入管理

外部单位送交受控物资时，值班员不再仅凭单位名称接收，而是按
**单位身份 + 物资品类 + 接收日期** 选择适用的准入版本，并对每一次通过或拒绝留下具体判定依据。

### 规则与优先级

1. **身份识别**：填报名称命中单位当前名称或任一历史名称均视为同一单位；名称（含历史名称）全局唯一，杜绝冒名。
2. **暂停/终止优先**：被暂停或终止合作的单位不能发起新移交，即使持有有效授权或紧急临时许可；仅可凭**已批准且未使用的退回批准单**完成退回（接收后批准单自动核销，不得重复使用）。
3. **授权范围与有效期**：准入版本必须在接收日期处于有效期内（起止日期含当天）、未撤销，且授权品类范围覆盖本次送交品类，否则拒绝。
4. **授权重叠裁定**：多个版本同时适用时，**紧急临时许可优先于常规授权**；同类版本以有效期开始日期更晚（签发更新）者优先，再相同则截止日期更晚、编号更大者优先。
5. **名称变更**：改名时旧名称自动保留为历史名称，新名称不得与任何单位的当前名/历史名冲突。
6. **全量留痕**：预检与正式接收均返回逐条 `basis` 判定依据；正式接收无论通过或拒绝都写入 `wh_handover` 台账。

### 接口

| 方法 & 路径 | 说明 |
| --- | --- |
| `POST/GET /api/transfer-units/` | 移交单位建档、列表（支持 `name`、`status` 过滤） |
| `GET /api/transfer-units/{id}/` | 单位详情（含名称版本链） |
| `POST /api/transfer-units/{id}/rename/` | 名称变更（`new_name`、`effective_from`、`reason`） |
| `POST /api/transfer-units/{id}/status/` | 暂停/恢复/终止（`active`/`suspended`/`terminated`） |
| `POST/GET /api/authorizations/` | 准入授权登记（`unit`、`kind=regular/emergency`、`category_ids`、`valid_from`、`valid_to`） |
| `POST /api/authorizations/{id}/revoke/` | 撤销授权（停止后续适用，历史记录保留） |
| `POST/GET /api/return-approvals/` | 退回批准单登记与查询 |
| `POST /api/admission/evaluate/` | 收件准入**预检**，只判定不写台账，返回 `accepted` 与 `basis` |
| `POST /api/handovers/receive/` | 正式接收：通过才入台账，拒绝同样留痕并返回依据；退回自动核销批准单 |
| `GET /api/handovers/` | 接收台账查询（`unit_name`、`decision`、`purpose`、`category`、`start_date`、`end_date`） |
| `GET /api/handovers/{id}/` | 单次接收详情，含逐条判定依据 |

`POST /api/admission/evaluate/` 与 `POST /api/handovers/receive/` 主要入参：

```json
{
  "unit_name": "东城管理所",
  "category": 1,
  "on_date": "2026-10-03",
  "purpose": "handover",
  "return_document_no": ""
}
```

退回业务 `purpose` 取 `return` 且必须提供 `return_document_no`；`on_date` 缺省为当天。
