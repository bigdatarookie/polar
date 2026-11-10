# Polar

Спецификация проекта `polar` и финансового исследовательского рига `polar-rig` (**Polar Rig**). Подготовлена 2026-11-06. Разработка платформы и внешний UI-эксперимент идут независимо до интеграции выбранного прототипа.

Версия требований: **0.33**. Это пакет требований, а не доказательство работающего сервиса или финансовой гипотезы. `rig.yaml`, регистрация проекта, выбор моделей, создание и запуск команды выполняются оператором по поручению пользователя. Текущий runtime статус проверяется через OpenRig.

v0.25: самостоятельное исследование препятствий и проверка решений через потребителя; существенные выводы в существующих NOTES/LEARNED, улучшение повторяемых инструментов. Не вводит новый gate или обход научных/пользовательских границ; дополняет v0.24.

v0.24: конечная поставка данных с автоматическим продолжением порций внутри общего бюджета; основания лимитов и функциональных PR-зависимостей; раздельная QA загрузчика/датасета и пригодность для конкретного эксперимента.

Массовый импорт v0.19: возобновляемый загрузчик внутри Polar, первый адаптер OpenFIGI; контракт checkpoint/cache/retry/изоляции ошибок — PLATFORM.md, владение — TEAM.md, хранение — MEMORY.md. Там же уточнены различение симптома/инцидента/причины и закрытие по восстановлению работы. Текущие поставки продолжаются; код загрузчика требует отдельной реализации и независимой приемки.

v0.20: минимальный расширяемый Gym и experiment-specific preflight — основной экспериментальный путь. Изолированное QA-окружение и чтение состояния работы — две отдельные инфраструктурные задачи с приоритетом v0.27, без искусственной остановки независимого эксперимента. Архитектура/кандидаты библиотек — PLATFORM.md, приемка — EVALUATION.md, роли — TEAM.md. Применение спецификации не означает реализацию.

v0.22: исполнимый reject-to-author handoff, независимая приемка конечного harness и самостоятельная авторская synthetic отладка без manual freeze, affected-only recheck, автоматически наблюдаемый image/receipt и точная классификация зависимостей. Политика не является внедрением инструментов/QA PASS или разрешением повторить старый опыт.

v0.23: ограниченный повтор QA после исправления harness/среды остается внутри действующего задания и ресурсов, а лимит отдельной попытки не превращается в пользовательский запрет без первичной инструкции. Оператор после каждого обращения пользователя напоминает обо всех действительно ожидающих решениях Polar, не только UI, и связывает `external:user-*` с фактически доставленным вопросом.

v0.21: NautilusTrader — предпочтительная основа Gym и приоритетная задача практического внедрения: adapter, сохраненные данные, первый воспроизводимый backtest. Обзор data integrations входит в эту работу; доступ к новым провайдерам не является предпосылкой первого запуска.

## Карта пакета

| Документ | Назначение |
|---|---|
| [SPEC.md](SPEC.md) | Миссия, границы, первый рынок, этапы и критерии готовности |
| [CULTURE.md](CULTURE.md) | Короткая финансовая культура для будущего рига |
| [TEAM.md](TEAM.md) | Двенадцать ролей, QA-led PR, DevOps и прямое обеспечение исследований данными, модели |
| [EVALUATION.md](EVALUATION.md) | Метрики, независимая оценка, OOS, рандомизация и синтетические испытания |
| [MEMORY.md](MEMORY.md) | Расширение нативной памяти OpenRig, обязательные бюджеты и восстановление |
| [PLATFORM.md](PLATFORM.md) | Архитектура, контейнерное развертывание, PR/GitOps, данные, экспериментальные записи и эксплуатация |
| [SOURCES.md](SOURCES.md) | Проверенные основания и пределы сделанных выводов |

UI-доработки инициируются агентами через оператора и рассматриваются пользователем вручную; передача UI-ригу требует явного поручения. После каждого обращения пользователя оператор напоминает обо всех действительно нерешенных решениях Polar, блокирующих зависимый результат, включая UI. Полный контракт — в SPEC.md, TEAM.md, PLATFORM.md и MEMORY.md.

Изменение, восстановление и проблемы регистрации/авторизации фиксируются в общем OpenRig access/NOTES.md; обычные операции через действующую авторизацию остаются в штатных proof. Правила эпизодов, state-aware randomized pacing, приватности и последующего анализа — в SPEC.md, TEAM.md, PLATFORM.md и MEMORY.md.

## Порядок чтения

Пользователь и оператор: `SPEC.md` → документы по интересующей ответственности.

Операторские поручения и задание на внешний UI-эксперимент передаются сообщениями OpenRig, не входят в пакет спецификации. Весь пакет не должен автоматически попадать в контекст каждого seat.

Будущие агенты: небольшой общий контекст и выбранные разделы своей роли; точная схема — в `MEMORY.md`. Имя этого документа обозначает политику памяти, не общий растущий журнал.

Финансовая пригодность данных, инфраструктурные доступы, сроки forward-наблюдения и бюджеты сейчас не подтверждены. Не подменять их UI-фикстурами, source/hypothesis cards или наличием этой спецификации. v0.9 закрепляет постоянный исследовательский мандат Quant A/B и Data Researcher: они сами оформляют конечные шаги и напрямую сотрудничают без обязательного Lead gate; экспериментальные результаты, бюджеты кампаний и финансовый verdict остаются отдельными строго ограниченными состояниями.

Current nearest outcome: the v0.12 real historical OHLCV vertical path in SPEC.md. User-confirmed private personal use only for the selected EODHD route; paired UI execution is approved. Real-data/runtime/research acceptance still requires actual evidence.

Resource amendment0.13: one64GiB total local storage; CPU/RAM admission by measured host availability, no inherited fixed project/task/browser subcaps. Historical attempts remain evidence; no restart or extra execution authority. The nearest real-data product goal remains v0.12.

v0.17 procedure: SPEC defines Lead's hourly mission-flow diagnosis and the standing multi-source Data Pod mandate; TEAM splits diagnosis/scheduler/data/scientific responsibility; PLATFORM defines the native3600second restart-reconciled wake; MEMORY defines the findings-only process-health journal. Informational status questions alone do not trigger intervention. Preserve v0.16 access-episode boundaries, existing work and scientific/resource/private-use rules; no restart or per-seat acknowledgment round.

v0.18 admission: EVALUATION distinguishes positively cross-checked standard best-effort/non-strict-PIT backtests from explicitly strict claims, admits robust documented market-overlap identity without a mandatory permanent ID, and permits documented/conservatively estimated known-by with anti-leakage lag/uncertainty/fallback. No actual data comparison, experiment or financial result is certified by this package update; prior attempts and v0.17 procedures remain.

v0.26: automatic rejection of model suggestions, evidence-based quota reset, hourly stale-blocker checks and DevOps-owned verified wake recovery.

v0.27: outcome-first mission, mandatory infrastructure priority through QA/integration/use, removal of agent-invented engineering quotas, direct queue continuation and hourly efficiency recovery.

## Ревизия v0.28

Ответственность за outcome и native возврат после конечных шагов; обоснование численных ограничений и применимости покрытия; исполнимое действие вместо ожидания эвристики. PLATFORM/TEAM/EVALUATION описывают процесс без новых таймеров и реестров.

## Ревизия v0.30

Максимальный приоритет исправлению review и автоматической подготовки QA-пакетов. Авторская synthetic отладка перед независимой приемкой; технические attempts отделены от научных trials. PLATFORM/TEAM/EVALUATION задают исполнение.

## Канонический источник и опыт

Источник спецификации — этот каталог polar-rig внутри репозитория Polar. Установленная ~/.openrig/specs/polar-rig — проекция, а не независимо редактируемая спецификация. Старый путь в openrig-exp — совместимая ссылка на этот каталог. rig.yaml, COMMON.md и guidance сохранены из действующего пакета v0.30 без изменения состава/моделей; это исходники конфигурации, не доказательство запуска. Process journal: ../docs/operations/process/NOTES.md; рабочие уроки: LEARNED.md. Live журналы/evidence не входят в установочный manifest. Политика — PLATFORM; контекст обновляется через существующий operator workflow.

## v0.32 — Миграция CI и восьмичасовой outcome

Основной технический путь — GitHub Actions и воспроизводимый контейнер из публичных закрепленных зависимостей; mandatory local package chain заменяется. Lead фиксирует T0 при фактическом начале по поручению оператора, ежечасно корректирует исполнение целей2/4/6/8ч. Полный план — PLATFORM: Миграция CI: план T0+2/4/6/8 и ежечасный контроль. Это план исполнения, не новое разрешение каждой попытки или stop-after8h; документация сама по себе не запускает миграцию.

Текущий авторизованный этап — [широкие исследования, ML/RL и плавный график](missions/02-wide-research/SPEC.md). Действующие правила v0.33 находятся в PLATFORM и guidance.
