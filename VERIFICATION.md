# Локальная проверка — 10 октября 2026

Репозиторий клонирован в текущую папку. Исходный Git status был чистым,
AGENTS.md отсутствует. Исправления публикуются отдельной веткой и PR без слияния.

## Результат

- Приложение запущено через Uvicorn на `127.0.0.1:58000`, Python 3.12.14.
- Portable PostgreSQL 16.15 запущен на `127.0.0.1:55432` только для проверки.
  Использованы отдельные БД `orderflow_api_test` и `orderflow_suite_test`.
- 48 тестов прошли на SQLite и 48 на PostgreSQL.
  Покрытие: SQLite — 91%, PostgreSQL — 89%, включая CLI в составе приложения;
  ветки сервиса заказов покрыты полностью. Учёт greenlet включён в coverage.
- Ruff lint, Ruff format, strict mypy, pip check и git diff --check прошли.
- Alembic: upgrade с нуля → downgrade base → upgrade head; alembic check
  не обнаружил расхождений моделей и схемы.
- Реальный HTTP-smoke: health/OpenAPI, регистрация и дубликат, вход,
  JWT/me и отказ без токена/с неверным паролем, создание товара администратором и отказ клиенту,
  заказ и сумма, чтение, запрет клиенту подтверждать оплату,
  ручное подтверждение администратором и повторная отмена с возвратом остатков,
  404 и 422. Сумма, статус, позиции и остаток подтверждены прямым чтением БД.
- Сохранённый заказ успешно прочитан через HTTP после перезапуска API.
- API-тесты дополнительно проверяют чужие заказы, ошибочные/истёкшие JWT,
  отсутствие exp у JWT существующего пользователя, валидацию цены/ID,
  откат заказа и остатков после ошибки, одновременные дубликаты,
  конкуренцию за последнюю единицу товара (с барьером чтения на PostgreSQL),
  гонку отмены с оплатой, однократное восстановление stock, конечные статусы,
  запрет повышения прав при регистрации, отзыв роли при сохранённом JWT,
  безопасное создание администратора без повышения существующей учётной записи.
- На отдельной копии исходного HEAD ранняя версия новых регрессионных
  тестов дала 9 падений из 22; исходные файлы рабочего проекта не откатывались.

## Исправления и файлы

| Файлы | Изменение |
|---|---|
| app/api/routes/orders.py, app/services/orders.py | Проверка владельца/администратора; допустимые переходы; атомарная отмена с однократным возвратом stock; условное списание stock; проверка максимальной суммы |
| app/api/deps.py, app/core/security.py | Некорректный субъект JWT даёт 401; обязательные sub/iat/exp; проверка роли администратора из БД |
| app/schemas.py, app/api/routes/products.py, app/api/routes/orders.py | Decimal для входной цены и ограничения PostgreSQL Numeric/Integer; неверные значения дают 422 |
| app/services/users.py, app/services/products.py | Конкурентный конфликт уникальности даёт 409 вместо необработанного IntegrityError |
| alembic/versions/587376b8170e_initial_schema.py | Downgrade удаляет enum order_status, позволяя повторный upgrade |
| tests/conftest.py, tests/test_regressions.py, tests/test_permissions_and_status.py, tests/test_orders.py, tests/test_products.py | Изолированные SQLite-соединения, PostgreSQL-режим и регрессионные проверки |
| scripts/smoke_api.py | Повторяемая проверка работающего HTTP API и сохранённых данных |
| pyproject.toml | Корректный учёт SQLAlchemy greenlet в coverage |
| .github/workflows/ci.yml | PostgreSQL-тесты в CI; smoke через Compose с миграциями, проверка каталога, очистка контейнеров |
| .gitignore | Исключение локальных инструментов/БД и editable-install metadata |
| .dockerignore | Исключение секретов, локальных БД, portable-инструментов и venv из Docker build context |
| app/models.py, app/schemas.py, alembic/versions/b163f89d211a_user_admin.py | Роль is_admin; новая миграция сохраняет существующих пользователей обычными |
| app/cli.py | Локальная атомарная команда создания администратора; скрытый ввод пароля |
| app/core/exceptions.py | Бизнес-ошибка 403 для запрета доступа |
| README.md, VERIFICATION.md | Фактические возможности, ограничения и команды проверки |

## Что не проверено запуском

Docker Desktop 4.94.0 установлен для текущего пользователя; Docker CLI 29.8.2,
Compose v5.5.1, WSL 2.7.13. Virtual Machine Platform включён с результатом
`RestartNeeded: true`. До перезагрузки Docker Engine не запускается.
Исходный Compose и изолированная конфигурация проверки прошли `compose config`.
Dockerfile/Compose/CI изучены; сборка, контейнерный smoke и GitHub Actions
пока не запускались. Перезагрузка компьютера автоматически не выполнялась.
Dockerfile не изменялся. Внешние сервисы и фоновые задачи в коде отсутствуют,
тестовые имитации не использовались.

В коде нет корзины, удаления заказов/товаров, редактирования товаров,
реальных платежей и идемпотентных POST-заказов.
Роль администратора реализована. Клиент отменяет только свой pending-заказ;
администратор подтверждает paid, shipped или отменяет pending/paid.
shipped/cancelled конечные; повтор разрешённого статуса безопасен.
Оплата подтверждается вручную, денежный возврат при отмене не автоматизирован.
`/health` не проверяет готовность БД.

## Команды для подготовленного локального окружения

Открыть PowerShell в папке проекта. `.venv`, portable PostgreSQL и `.env`
уже подготовлены, содержат только локальные тестовые значения и исключены из Git.
Если тестовый PostgreSQL остановлен:

```powershell
$env:PYTHONUTF8 = '1'
$projectRoot = (cmd /c 'for %I in (.) do @echo %~sI').Trim()
& "$projectRoot\.local\postgres\pgsql\bin\pg_ctl.exe" -D "$projectRoot\.local\pgdata-test" -l "$projectRoot\.local\postgres.log" -o '-p 55432 -h 127.0.0.1' -w start
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 58000
```

Во втором PowerShell из той же папки:

```powershell
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe scripts/smoke_api.py --base-url http://127.0.0.1:58000
.\.venv\Scripts\python.exe -m pytest --cov=app --cov-report=term-missing
# Используем ту же локальную конфигурацию, но другую БД для pytest:
$localDbLine = @(Get-Content .env | Where-Object { $_ -like 'DATABASE_URL=*' })[0]
$env:TEST_DATABASE_URL = $localDbLine.Substring(13).Replace('orderflow_api_test', 'orderflow_suite_test')
.\.venv\Scripts\python.exe -m pytest --cov=app --cov-report=term-missing
Remove-Item Env:TEST_DATABASE_URL
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m pip check
```

Завершить Uvicorn через Ctrl+C. Остановить только подготовленный тестовый кластер:

```powershell
$projectRoot = (cmd /c 'for %I in (.) do @echo %~sI').Trim()
& "$projectRoot\.local\postgres\pgsql\bin\pg_ctl.exe" -D "$projectRoot\.local\pgdata-test" -m fast -w stop
```

Для чистой установки и запуска с Docker используйте команды README.
Итоговый diff просмотрен: секреты, БД, бинарники, временные копии и логи
исключены из Git. Локальные тестовые данные сохранены для повторной проверки.

Новая миграция проверена на существующей тестовой БД: оба прежних пользователя
сохранились с is_admin=false. Полный цикл всех миграций дополнительно прошёл
на orderflow_migration_test. Реальная команда app.cli create-admin создала
тестового администратора; повторный запуск вернул контролируемую ошибку дубликата.

Для собственного администратора после запуска тестовой БД:

```powershell
.\.venv\Scripts\python.exe -m app.cli create-admin --email admin@example.com
```

Пароль вводится скрыто, в отчёт и Git не сохраняется.

## Выполненная контейнерная проверка

13 октября Docker image собран, API запущен с отдельным PostgreSQL.
Через настоящий HTTP прошли регистрация, вход/me, создание администратора CLI,
запрет создания товара клиентом, создание заказа, изоляция пользователей,
повторная отмена с однократным возвратом stock, ошибки 401/404/409/422.
Это дополняет ранее выполненные 48 тестов на SQLite и 48 на PostgreSQL.
Обычный запуск и Docker-команды приведены в README. Реальные данные не использовались.
