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

外部单位送交受控物资时，值班员不再只凭单位名称接收，系统按"准入版本"
判定后才允许进入正式台账。

### 判定优先级（高 → 低）

| 级别 | 规则 | 说明 |
| --- | --- | --- |
| P0 | 暂停闸门 / 已批准退回 | 单位暂停合作后，新移交一律拒绝；持有效退回批准文号的退回仍可完成（正常单位的退回同样必须凭批准文号）。暂停优先级高于紧急临时许可。 |
| P1 | 紧急临时许可 | 在有效期窗口内覆盖常规授权，可限定品类、次数、批准人；过期、撤销、超次数即失效。 |
| P2 | 常规准入授权 | 同一单位、同一品类可有多个授权版本，按物资品类与收件日期选取生效日期最新、范围覆盖该品类的版本；区分过期、未生效、范围不符三种拒绝原因。 |
| P3 | 名称变更链 | 单位更名自动登记曾用名，来件使用旧名称时解析到当前单位主体；名称解析只负责身份识别，不单独产生授权。 |

每条收件记录（含拒绝）都保存 `decision_basis`，说明本次通过或拒绝
所依据的版本、有效期窗口与命中的优先级规则。

### 主要接口

- `POST /api/transfer-units/`、`PUT /api/transfer-units/{id}/`：移交单位登记/更名（更名自动写入名称变更链）
- `POST /api/transfer-units/{id}/suspend/`、`/resume/`：暂停/恢复合作
- `POST /api/transfer-units/{id}/name-changes/`：补登曾用名
- `POST /api/access-grants/`：登记准入授权版本（全部品类/指定品类 + 生效与失效日期）
- `POST /api/emergency-permits/`、`POST /api/emergency-permits/{id}/revoke/`：紧急临时许可
- `POST /api/return-approvals/`：退回来件批准（文号、物资、批准数量、有效期）
- `POST /api/custody/check/`：收件前试判，不落库，返回结构化判定依据
- `POST /api/custody/receive/`：正式收件，通过或拒绝均留痕（拒绝不进入库存台账）
- `GET /api/custody/transfers/`：移交/退回台账查询，支持单位、品类、结论、日期过滤

