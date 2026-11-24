# OrderFlow Core

[![CI](https://github.com/AlexGoster/orderflow-core/actions/workflows/ci.yml/badge.svg)](https://github.com/AlexGoster/orderflow-core/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

**REST API для обработки онлайн-заказов** — ядро платформы OrderFlow: каталог, заказы, JWT-авторизация. Проект заложил архитектурные конвенции, CI-пайплайн и PR-процесс, на которых построены остальные сервисы платформы ([jobs](https://github.com/AlexGoster/orderflow-jobs), [scale](https://github.com/AlexGoster/orderflow-scale), [services](https://github.com/AlexGoster/orderflow-services), [platform](https://github.com/AlexGoster/orderflow-platform)).

## Архитектура

```mermaid
flowchart LR
    C[Клиент / Swagger] -->|JWT| A[FastAPI]
    A --> S[Сервисный слой]
    S --> D[(PostgreSQL)]
    A --> E[Единый формат ошибок]
    subgraph "Слои приложения"
        S
        R[API routes] --> S
        R --> V[Pydantic v2 схемы]
    end
```

- **API-слой** (`app/api`) — маршруты, DI через `Depends`, envelope бизнес-ошибок `{"error": {code, message}}`; ошибки валидации используют стандартный FastAPI `detail`
- **Сервисный слой** (`app/services`) — бизнес-логика, транзакции, инварианты (остатки на складе, итог заказа)
- **Домен** (`app/models.py`) — SQLAlchemy 2.0 `Mapped[]`-модели
- **Инфраструктура** (`app/core`) — конфиг (pydantic-settings), JWT (PyJWT + PBKDF2), доступ к БД

## API

| Метод | Путь | Описание |
|---|---|---|
| POST | `/api/v1/auth/register` | Регистрация (пароль — PBKDF2, 390k итераций) |
| POST | `/api/v1/auth/login` | Выдача JWT (HS256, TTL 30 мин) |
| GET | `/api/v1/auth/me` | Текущий пользователь |
| GET/POST | `/api/v1/products` | Чтение каталога публичное, создание — только администратор |
| POST | `/api/v1/orders` | Создание заказа (атомарное списание stock) |
| GET | `/api/v1/orders` | Свои заказы; администратор видит все |
| GET | `/api/v1/orders/{id}` | Владелец или администратор; чужой заказ для клиента — 404 |
| PATCH | `/api/v1/orders/{id}/status?new_status=cancelled` | Отмена своего ожидающего заказа; остальные переходы — администратор |
| GET | `/health` | Health-check |

Полная спецификация: `/docs` (Swagger UI), `/redoc`.

Корзина, удаление заказов/товаров, редактирование товаров, платежи, фоновые задачи
и внешние интеграции не реализованы. Повторный POST заказа создаёт новый заказ,
если хватает остатков; ключей идемпотентности нет.
`/health` проверяет доступность процесса, а не соединение с БД.
Цена должна быть положительной, с максимум двумя знаками после запятой,
не более `99999999.99`; такой же предел действует для итоговой суммы заказа.

### Права и статусы

Регистрация всегда создаёт обычного пользователя; `is_admin` из запроса игнорируется.
Роль проверяется в БД на каждом запросе, а не берётся из JWT.
Без токена защищённые маршруты возвращают 401, без нужной роли — 403.

| Текущий статус | Допустимый новый статус | Кто может менять |
|---|---|---|
| pending | paid | Администратор после подтверждения оплаты вне приложения |
| pending | cancelled | Владелец или администратор |
| paid | shipped | Администратор |
| paid | cancelled | Администратор |
| shipped / cancelled | Другого перехода нет | Конечные статусы |

Повтор разрешённого запроса на тот же статус безопасен. Отмена возвращает
количество каждой позиции на склад ровно один раз в одной транзакции со статусом,
включая одновременные запросы. Недопустимый переход возвращает 409.
Платёжного провайдера нет: `paid` — ручное подтверждение администратора;
отмена оплаченного заказа не выполняет денежный возврат автоматически.

Создать администратора после миграций из доверенного локального терминала:

```powershell
.\.venv\Scripts\python.exe -m app.cli create-admin --email admin@example.com
# Пароль вводится скрыто. Для автоматизации допустима ORDERFLOW_ADMIN_PASSWORD.
```

Команда создаёт новую учётную запись и не повышает права существующей.
Для Docker: `docker compose exec api python -m app.cli create-admin --email admin@example.com`.
Войти можно через обычный `/api/v1/auth/login`; `/auth/me` показывает `is_admin`.

## CI/CD

Пайплайн в GitHub Actions (`.github/workflows/ci.yml`) на каждый PR:

1. **Ruff lint + format check** — стиль и типовые ошибки
2. **Mypy (strict)** — статическая типизация без исключений
3. **Pytest + coverage** — unit и integration-тесты, порог покрытия в репозитории
4. **Docker build + smoke-тест** — Compose запускает API и PostgreSQL,
   выполняет миграции, проверяются `/health` и `/api/v1/products`

## Разработка

```bash
git clone https://github.com/AlexGoster/orderflow-core.git
cd orderflow-core
python -m venv .venv && . .venv/bin/activate
pip install . && pip install -r requirements-dev.txt
cp .env.example .env
docker compose up -d db
alembic upgrade head
uvicorn app.main:app --reload
```

Тесты не требуют Postgres — по умолчанию работают на временной SQLite-БД:

```bash
pytest --cov=app
```

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e . -r requirements-dev.txt
Copy-Item .env.example .env
# В .env задайте DATABASE_URL выделенной локальной БД и локальный SECRET_KEY.
docker compose up -d db
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Полный контейнерный запуск: `docker compose up --build --wait`.
Compose выполняет миграции перед запуском API.

### Проверки

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=app --cov-report=term-missing
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy app
```

Для PostgreSQL создайте **пустую отдельную** БД с именем, заканчивающимся на `_test`:

```powershell
$env:TEST_DATABASE_URL = 'postgresql+asyncpg://USER:PASSWORD@127.0.0.1:5432/orderflow_suite_test'
.\.venv\Scripts\python.exe -m pytest --cov=app
Remove-Item Env:TEST_DATABASE_URL
```

Тесты создают и удаляют таблицы в этой БД. Не используйте БД приложения.
Для реальной HTTP-проверки запустите API с `DATABASE_URL` другой выделенной БД
(`orderflow_api_test`), выполните миграции и затем в другом терминале с тем же `.env`:

```powershell
.\.venv\Scripts\python.exe scripts/smoke_api.py --base-url http://127.0.0.1:8000
```

Smoke создаёт уникального тестового администратора и клиента, проверяет
запреты доступа, ручное подтверждение оплаты и повторную отмену заказа,
а затем проверяет сохранённые данные напрямую в БД.
Данные остаются в тестовой БД для повторного чтения после перезапуска.

## Тесты

- Тесты идут через `httpx.AsyncClient` + `ASGITransport` и настоящую тестовую БД
  (по умолчанию отдельный временный SQLite-файл; PostgreSQL через `TEST_DATABASE_URL`)
- Кейсы: happy-path, дубликаты (409), чужие заказы (404), нехватка stock (409), отсутствие токена (401)

## Метрики

| Метрика | Значение |
|---|---|
| Покрытие кода | Измеряется командой `pytest --cov=app` |
| Время CI (lint→test→docker) | Смотрите фактическую длительность в GitHub Actions |
| Миграции | Alembic, воспроизводимы с нуля |

## Как дальше до production

- Refresh-токены и ротация ключей (JWKS)
- OpenTelemetry-трейсы и структурные JSON-логи
- Rate limiting на auth-эндпоинты
- Blue-green деплой миграций без даунтайма

## Лицензия

[MIT](LICENSE)
