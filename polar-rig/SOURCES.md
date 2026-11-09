# Основания спецификации

Дата проверки: 2026-11-06. Принятые продуктовые решения основаны на диалоге пользователя; приведенные исследования не доказывают преимущество мультиагентной команды или прибыльность будущих стратегий.

## Gym: кандидаты библиотек, 2026-11-08

Проверены официальные документация/репозитории при обсуждении Gym; библиотеки не установлены/не квалифицированы в Polar этой проверкой. Точная версия/API/license/platform проверяются при принятии зависимости; сведения develop/latest не подменяют locked release.

- NautilusTrader: https://nautilustrader.io/docs/latest/getting_started/ и https://github.com/nautechsystems/nautilus_trader — event-driven engine, Python3.13 support, LGPL-3.0. Кандидат, не подтверждение нужных corporate-action/ledger semantics. Сравнить с существующим Polar engine на контрольном сценарии.
- Gymnasium: https://gymnasium.farama.org/introduction/create_custom_env/ — reset/step, spaces, wrappers и env checker; будущий RL interface, не финансовый симулятор.
- empyrical-reloaded: https://github.com/stefan-jansen/empyrical-reloaded — финансовые risk/performance metrics; definitions/precision/risk-free и Python compatibility требуют проверки.
- Hypothesis: https://hypothesis.readthedocs.io/en/latest/stateful.html — property/stateful tests для учетных инвариантов, не oracle финансовой методики.
- scikit-learn TimeSeriesSplit: https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html — temporal folds/gap; не полная защита от label leakage и не готовая purged financial CV.
- VectorBT: https://github.com/polakowo/vectorbt#license — текущий текст Apache2.0+CommonsClause; не считать обычной permissive open-source зависимостью и не включать автоматически.

## NautilusTrader data integrations — уточнение 2026-11-08

- https://nautilustrader.io/docs/latest/integrations/ — modular provider/venue adapters; перечень включает available/planned, не все строки означают готовый adapter.
- https://nautilustrader.io/docs/latest/integrations/databento/ — исторические API-запросы и instrument definitions, DBN file loader, live feed; data-only без execution client. Это не выдача прав/подписки или доказательство нужного покрытия.
- https://nautilustrader.io/docs/latest/integrations/interactive_brokers/ — data/execution/instrument discovery/historical requests через TWS/IB Gateway. Требуются соответствующие учетная запись/права/окружение; в Polar не подключалось этой проверкой.

Официальные latest/develop сведения проверены как документация. Совместимость конкретного pinned release, реальное получение provider data и backtest acceptance требуют отдельных фактических проверок. v0.21 приоритет внедрения — решение пользователя, не результат квалификации библиотеки.

## OpenRig: проверенный установленный интерфейс

Внешняя сессия, CLI `0.7.7 (f3d8bac4)`. Использованы read-only команды:

```text
rig whoami --json
rig --version
rig context list
rig context get skills/openrig-operating-model/SKILL.md
rig context get skills/core/specification-system/SKILL.md
rig context get world-example
rig context work-install --json
rig queue --help
rig proof --help
```

Операционная модель описывает нативные CULTURE/LEARNED, project/mission/slice SPEC/NOTES/PROOF и размещение знания в минимальном нужном scope. Queue отвечает за owned work; proof — за attributed judgment. Эти границы проверены по установленной документации, а не по одному воспоминанию о ранней версии.

Локальная библиотека на этапе проверки находилась внутри установленного `@openrig/cli`, `daemon/context-packs`. Путь установки не переносится в startup будущих агентов: они используют library addresses и выбранный project loadout. Инвентарь пакетов и возможности должны проверяться на версии запуска.

Время работы, состояние workers, финансовый проект, доступы и автоматическое enforcement памяти еще не проверены. Проект не зарегистрирован и rig не запущен.

## Финансовая методика

- [CFA Institute — Backtesting & Simulation, 2026](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/backtesting-and-simulation): rolling-window исследования дополняются сценариями, симуляцией и анализом чувствительности. Это основание сочетать проверки, не обещание универсального теста.
- [Bailey и López de Prado — The Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf): оценка Sharpe с учетом selection bias и ненормальности. Не исправляет утечки данных автоматически.
- [White — A Reality Check for Data Snooping](https://users.ssc.wisc.edu/~behansen/718/White2000.pdf): проверка превосходства выбранной модели с учетом поиска по нескольким спецификациям.
- [Politis и Romano — The Stationary Bootstrap](https://users.ssc.wisc.edu/~behansen/718/Politis%20Romano.pdf): пересэмплирование зависимых стационарных рядов при соответствующих предположениях. Не универсальный генератор будущего рынка.
- [Andrew Lo — The Statistics of Sharpe Ratios](https://alo.mit.edu/research-page/the-statistics-of-sharpe-ratios/): неопределенность Sharpe и роль временной зависимости; estimator и annualization должны быть определены.
- [Novy-Marx — Backtesting Strategies Based on Multiple Signals](https://www.nber.org/papers/w21329): комбинирование и отбор сигналов усиливают проблему переобучения и множественных проверок.

Первые два ресурса открыты повторно при написании пакета; остальные изучались в предшествующем обсуждении. До реализации Validator проверяет актуальность выбранной методики и применимость к конкретным данным. Названия методов не считаются выполненными проверками.

## Данные и практика команд

- [SEC — EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces): официальный доступ к submissions history и XBRL. Наличие API не доказывает, что собранный dataset автоматически point-in-time корректен.
- [Jane Street — Wrestling the World into Rows](https://signalsandthreads.com/wrestling-the-world-into-rows/): работа с alternative data, инженерия данных, revisions и связи сущностей. Использовано в обсуждении для разделения sourcing и инженерной ответственности, не как готовая схема состава seats.
- [Two Sigma — Quantitative Research & Data Science](https://www.twosigma.com/careers/quantitative-research-data-science/): публичное описание исследовательских функций и инженерной поддержки.
- [Google SRE — Eliminating Toil](https://sre.google/sre-book/eliminating-toil/): эксплуатация включает автоматизацию и улучшение системы; DevOps не должен стать ручным диспетчером каждого опыта.

## Сообщества: материал для гипотез

- [r/quant — доступность alternative datasets](https://www.reddit.com/r/quant/comments/1g0gawn/are_there_any_quality_alternative_datasets_for/).
- [r/algotrading — point-in-time historical data](https://www.reddit.com/r/algotrading/comments/1tj2b3p/structured_pointintime_historical_data/).

Обсуждения изучались в диалоге. Это свидетельства отдельных участников, иногда с рекламным интересом. Рекомендации поставщиков, цены и заявления о доходности не приняты как проверенные факты и не внесены в бюджет/benchmark suite. Будущий Data Researcher использует сообщества для поиска идей с последующей независимой проверкой.

## User resource amendment — 2026-11-07 12:50UTC

Primary authority is native user decision qitem-20261107125004-f39f842c163da635, operational resource-policy-user-flexible-20261107.md and Lead ownership clarification13:01UTC. One64GiB(68,719,476,736bytes) total local storage; measured-host CPU/RAM instead of inherited fixed quotas. Dated user-observed host24GiB/14logical CPUs/about293.7GiB free is not a future-capacity guarantee. This changes resource policy only, not source rights/campaign/candidate/context or process-ownership rules; historical failure bytes remain unchanged.

## Опыт авторизованного доступа — 2026-11-07

- Внутренний Alpaca source: /Users/garry/.openrig/shared-docs/rigs/polar-rig/state/data/real-historical-v01/account-qualification-v1/browser-registration-research-pass-v1.md и alpaca-qualification-v1/source-access-return-v1.md. Это атрибутированные наблюдения Data Engineer: один submitted signup, разрешенная Gmail verification/dashboard/key и четыре HTTP200 GET в отдельном source sample. Они не доказывают универсальную пригодность метода, юридическую eligibility, полную entitlement или PIT coverage. В этом обновлении вход/API не повторялись.
- [Zendriver — официальный репозиторий](https://github.com/cdpdriver/zendriver), [документация browser](https://zendriver.dev/reference/core/browser/): проверены 2026-11-07 как первичные ссылки для будущей оценки альтернативного browser adapter. Библиотека не установлена/не выбрана проектным стандартом; маркетинговые claims не считаются measured provider compatibility.
