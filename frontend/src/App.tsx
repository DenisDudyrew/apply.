import {
  ProfileBar,
  ProfileManager,
  QueueCard,
  CaptchaWait,
} from "./DesktopFeatures";
import { useEffect, useRef, useState } from "react";
import type { FormEvent, MouseEvent } from "react";
import {
  ArrowUpRight,
  ArrowRight,
  ArrowDown,
  ArrowUp,
  LayoutDashboard,
  History,
  SlidersHorizontal,
  Search,
  ShieldCheck,
  Zap,
  Check,
  CheckCheck,
  CircleHelp,
  Sparkles,
  Globe2,
  FileQuestion,
  Timer,
  Play,
  Square,
  LogOut,
  X,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Send,
  Loader2,
  CircleAlert,
  CheckCircle2,
  Link2,
  ListFilter,
  Terminal,
  FolderSearch,
  Keyboard,
  FileText,
} from "lucide-react";
import { Button, Modal, Switch, cn } from "./components/ui";
import { useLiveState } from "./useLiveState";
import type {
  AppState,
  HistoryRow,
  Preferences,
  PageData,
  Vacancy,
  ActionData,
} from "./types";

const defaults: Preferences = {
  limit: 1000,
  skip_questionnaires: true,
  skip_foreign_vacancies: true,
  gentle: true,
};
const statuses: Record<string, { label: string; tone: string }> = {
  sent: { label: "Отправлено", tone: "lime" },
  review: { label: "Пропущено", tone: "neutral" },
  already: { label: "Уже есть отклик", tone: "lavender" },
  uncertain: { label: "Нужна проверка", tone: "amber" },
  pending: { label: "Не завершено", tone: "amber" },
  stopped: { label: "Остановлено", tone: "amber" },
};
const phases: Record<string, string> = {
  idle: "Готов к запуску",
  searching: "Ищем твои вакансии",
  verifying: "Проверяем резюме",
  sending: "Отправляем отклики",
  pausing: "Небольшая пауза",
  completed: "Этот раунд завершён",
  stopped: "Запуск остановлен",
  error: "Нужна проверка",
  stopping: "Останавливаем…",
  login: "Подключаем аккаунт",
  ready: "Подборка готова",
  captcha_wait: "Пауза из-за капчи",
  preparing_browser: "Подготовка ручных форм",
};
const num = (n: number = 0) => new Intl.NumberFormat("ru-RU").format(n);
function safeUrl(url: string) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" &&
      (u.hostname === "hh.ru" || u.hostname.endsWith(".hh.ru"))
      ? url
      : undefined;
  } catch {
    return undefined;
  }
}
function timeLabel(value: string) {
  try {
    return new Intl.DateTimeFormat("ru-RU", {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "Europe/Moscow",
    }).format(new Date(value));
  } catch {
    return "";
  }
}

export default function App() {
  const { state, connection, error, setError, action, request } =
    useLiveState();
  const [tab, setTab] = useState("overview"),
    [loginOpen, setLoginOpen] = useState(false),
    [helpOpen, setHelpOpen] = useState(false);
  const [settings, setSettings] = useState<Preferences>(defaults),
    [limit, setLimit] = useState("1000"),
    [username, setUsername] = useState(""),
    [busy, setBusy] = useState(false),
    [toast, setToast] = useState("");
  const [query, setQuery] = useState(""),
    [filter, setFilter] = useState(""),
    [page, setPage] = useState(1),
    [storedData, setData] = useState<PageData<HistoryRow | Vacancy> | null>(
      null,
    ),
    [dataKind, setDataKind] = useState("");
  const data = dataKind === tab ? storedData : null;
  const [listBusy, setListBusy] = useState(false),
    [listError, setListError] = useState("");
  const [showLogs, setShowLogs] = useState(false),
    [expanded, setExpanded] = useState<string | null>(null);
  const prefsKey = JSON.stringify(state?.preferences);
  useEffect(() => {
    if (state?.preferences) {
      setSettings(state.preferences);
      setLimit(String(state.preferences.limit));
    }
  }, [prefsKey]); // Only server preference changes replace local edits.
  useEffect(() => {
    setPage(1);
    setQuery("");
    setFilter("");
  }, [tab]);
  useEffect(() => {
    if (tab !== "history" && tab !== "candidates") return;
    let active = true;
    setListBusy(true);
    setListError("");
    const timeout = setTimeout(() => {
      void request(
        `/api/${tab === "history" ? "history" : "candidates"}?q=${encodeURIComponent(query)}&status=${encodeURIComponent(filter)}&page=${page}`,
      )
        .then((value) => {
          if (active) {
            setData(value);
            setDataKind(tab);
            setListError("");
          }
        })
        .catch((e) => {
          if (active) setListError(e.message);
        })
        .finally(() => {
          if (active) setListBusy(false);
        });
    }, 180);
    return () => {
      active = false;
      clearTimeout(timeout);
    };
  }, [tab, query, filter, page, state?.revision, request]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 4200);
    return () => clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    if (!state?.desktop) return;
    function externalLink(event: globalThis.MouseEvent) {
      const anchor = (event.target as Element).closest?.(
        'a[target="_blank"]',
      ) as HTMLAnchorElement | null;
      if (!anchor) return;
      event.preventDefault();
      void action({ action: "open_external", url: anchor.href }).catch((e) =>
        setError(e.message),
      );
    }
    document.addEventListener("click", externalLink);
    return () => document.removeEventListener("click", externalLink);
  }, [state?.desktop, action, setError]);
  const run = state?.run || {},
    authenticated = !!state?.auth.authenticated,
    connected = connection === "connected",
    running = !!state?.running;
  async function perform(value: ActionData, success = "") {
    setBusy(true);
    try {
      await action(value);
      if (success) setToast(success);
      return true;
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Не удалось выполнить действие",
      );
      return false;
    } finally {
      setBusy(false);
    }
  }
  function checkedSettings() {
    const n = Number(limit);
    if (!/^\d+$/.test(limit) || !Number.isInteger(n) || n < 1 || n > 1000) {
      setError("Укажите целое число от 1 до 1000.");
      return null;
    }
    return { ...settings, limit: n };
  }
  async function start(send: boolean) {
    if (!authenticated) {
      setLoginOpen(true);
      return;
    }
    if (!state?.resume.title) {
      navigate("settings");
      setToast("Сначала выбери резюме и сохрани профиль");
      return;
    }
    const values = checkedSettings();
    if (values) await perform({ action: "start", send, ...values });
  }
  async function saveSettings() {
    const values = checkedSettings();
    if (values)
      await perform(
        { action: "preferences", ...values },
        "Настройки сохранены",
      );
  }
  function navigate(value: string) {
    window.scrollTo(0, 0);
    setTab(value);
    setExpanded(null);
  }
  function lookAtAttention() {
    navigate("history");
    setTimeout(() => setFilter("attention"), 0);
  }
  const nowDate = new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "long",
    timeZone: "Europe/Moscow",
  }).format(new Date());
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            navigate("overview");
          }}
        >
          <span className="brand-mark">
            <ArrowUpRight size={24} strokeWidth={2.5} />
          </span>
          apply<span className="brand-dot">.</span>
        </a>
        <div className="workspace-label">ТВОЙ КАРЬЕРНЫЙ СПЕЙС</div>
        <nav aria-label="Навигация">
          {[
            { id: "overview", label: "Обзор", Icon: LayoutDashboard },
            { id: "candidates", label: "Вакансии", Icon: FolderSearch },
            { id: "history", label: "История откликов", Icon: History },
            { id: "settings", label: "Настройки", Icon: SlidersHorizontal },
          ].map(({ id, label, Icon }) => (
            <button
              key={id}
              className={cn("nav-item", tab === id && "active")}
              onClick={() => navigate(id)}
              aria-label={label}
              aria-current={tab === id ? "page" : undefined}
            >
              <Icon size={18} />
              <span>{id === "history" ? "История" : label}</span>
              {id === "history" && !!state?.summary?.attention && (
                <span className="nav-count">{state.summary.attention}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-note">
          <div className="mini-spark">
            <Sparkles size={17} />
          </div>
          <strong>
            Твой темп.
            <br />
            Твой следующий шаг.
          </strong>
          <p>
            Рутина — нам.
            <br />
            Собеседования — тебе.
          </p>
        </div>
        <div className="sidebar-bottom">
          <button className="nav-item" onClick={() => setHelpOpen(true)}>
            <CircleHelp size={18} />
            Как это работает
          </button>
          <div className="privacy-note">
            <ShieldCheck size={15} />
            <span>
              Данные только
              <br />
              на этом компьютере
            </span>
          </div>
          <span className="version">APPLY LOCAL / V2.0</span>
        </div>
      </aside>
      <main className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            Личный кабинет <span>/</span>{" "}
            <strong>
              {
                (
                  {
                    overview: "Обзор",
                    history: "История",
                    settings: "Настройки",
                    candidates: "Вакансии",
                  } as Record<string, string>
                )[tab]
              }
            </strong>
          </div>
          <div className="topbar-right">
            <span className={cn("live-badge", !connected && "offline")}>
              <i />
              {connected
                ? "На связи"
                : connection === "connecting"
                  ? "Подключаемся"
                  : "Восстанавливаем связь"}
            </span>
            <span className="top-date">{nowDate}</span>
            <button
              className="avatar"
              onClick={() => setLoginOpen(true)}
              aria-label="Аккаунт hh.ru"
            >
              {authenticated ? state?.auth.name?.[0] || "Я" : "Я"}
            </button>
          </div>
        </header>
        <div className="page-content">
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                {tab === "overview"
                  ? "ПУСТЬ РАБОТА НАЙДЁТ ТЕБЯ"
                  : "ВСЁ ПОД КОНТРОЛЕМ"}
              </div>
              <h1>
                {
                  (
                    {
                      overview: "Твой следующий шаг.",
                      history: "Каждый отклик на виду.",
                      candidates: "Есть из чего выбрать.",
                      settings: "Настрой под себя.",
                    } as Record<string, string>
                  )[tab]
                }
              </h1>
              <p>
                {
                  (
                    {
                      overview: "Меньше рутины. Больше возможностей.",
                      history:
                        "Результаты, причины пропусков и ничего потерянного.",
                      candidates:
                        "Свежая подборка по выбранному профилю поиска.",
                      settings:
                        "Твои правила — для каждого следующего запуска.",
                    } as Record<string, string>
                  )[tab]
                }
              </p>
            </div>
            <span className="outline-chip">
              <span className="hh-mini">hh</span> HEADHUNTER
            </span>
          </div>
          {!connected && state && (
            <div className="banner warning" role="status">
              <Loader2 size={18} className="spin" />
              Связь с панелью потеряна. Текущий запуск может продолжаться —
              подключаемся заново.
            </div>
          )}
          {error && (
            <div className="banner error" role="alert">
              <CircleAlert size={18} />
              <span>{error}</span>
              <button
                className="icon-btn"
                onClick={() => setError("")}
                aria-label="Скрыть ошибку"
              >
                <X size={17} />
              </button>
            </div>
          )}
          {!state ? (
            <div className="loading-state">
              <Loader2 className="spin" />
              <h2>Собираем твой спейс…</h2>
              <p className="muted">Подключаемся к локальной панели</p>
            </div>
          ) : (
            <>
              {(state.phase === "error" ||
                (state.phase === "stopped" && (run.attention || 0) > 0)) && (
                <div className="banner error" role="alert">
                  <CircleAlert size={18} />
                  <span>{state.message}</span>
                  <button className="text-link" onClick={lookAtAttention}>
                    Посмотреть историю <ArrowRight size={15} />
                  </button>
                </div>
              )}
              {state.phase === "captcha_wait" && (
                <CaptchaWait state={state} perform={perform} busy={busy} />
              )}
              {state.waiting && (
                <ManualCard
                  state={state}
                  perform={perform}
                  busy={busy}
                  connected={connected}
                />
              )}
              {tab === "overview" && (
                <>
                  <ProfileBar
                    state={state}
                    perform={perform}
                    configure={() => navigate("settings")}
                  />
                  <QueueCard state={state} perform={perform} busy={busy} />
                  <section className="metrics" aria-label="Статистика откликов">
                    <Metric
                      label="Отправлено сегодня"
                      value={state.summary?.today_sent}
                      icon={<Send size={18} />}
                      accent="lime"
                      detail="По Москве · подтверждено hh.ru"
                    />
                    <Metric
                      label="Отправлено за всё время"
                      value={state.summary?.sent}
                      icon={<CheckCheck size={19} />}
                      accent="lavender"
                      detail="Каждый отклик сохранён"
                    />
                    <Metric
                      label="Пропущено по правилам"
                      value={state.summary?.skipped}
                      icon={<ListFilter size={18} />}
                      accent="neutral"
                      detail="Причины доступны в истории"
                    />
                    <button
                      className="metric metric-button"
                      onClick={lookAtAttention}
                    >
                      <div className="metric-top">
                        <span>Нужна проверка</span>
                        <span className="metric-icon amber">
                          <CircleAlert size={18} />
                        </span>
                      </div>
                      <div className="metric-value">
                        {state.summary ? num(state.summary.attention) : "—"}
                        <ArrowUpRight size={21} />
                      </div>
                      <span className="metric-detail">
                        Не повторяем без проверки
                      </span>
                    </button>
                  </section>
                  <div className="dashboard-grid">
                    <section className="panel run-panel">
                      <div className="panel-top">
                        <span className="section-kicker">
                          <span className="lime-dot" />
                          ЦЕНТР УПРАВЛЕНИЯ
                        </span>
                        <span
                          className={cn(
                            "status-pill",
                            running && "is-running",
                            state.waiting && "is-waiting",
                          )}
                        >
                          {state.waiting
                            ? "Ждём тебя"
                            : phases[state.phase] || "Готов к запуску"}
                        </span>
                      </div>
                      <div className="run-intro">
                        <div>
                          <h2>
                            {running
                              ? "Мэтч уже ближе."
                              : "Хорошие возможности\nне ждут."}
                          </h2>
                          <p>
                            {running
                              ? "Мы берём рутину на себя. Ты всегда можешь остановить запуск."
                              : "Запусти отклики на подходящие вакансии.\nОстальное — уже настроено."}
                          </p>
                        </div>
                        <div
                          className={cn("orbit-art", running && "orbit-active")}
                          aria-hidden="true"
                        >
                          <div className="orbit-ring ring-one" />
                          <div className="orbit-ring ring-two" />
                          <div className="orbit-arrow">
                            <ArrowUpRight size={47} strokeWidth={1.6} />
                          </div>
                          <span className="orbit-star">✦</span>
                          <span className="orbit-dot" />
                        </div>
                      </div>
                      <div className="progress-box">
                        <div className="progress-heading">
                          <span>
                            {state.operation === "preview"
                              ? "Подборка вакансий"
                              : "Отклики в этом запуске"}
                          </span>
                          <span>
                            <strong>{num(run.sent)}</strong>
                            <span className="muted">
                              {" "}
                              / {num(run.limit || Number(limit) || 1000)}
                            </span>
                          </span>
                        </div>
                        <div
                          className="progress-track"
                          role="progressbar"
                          aria-label="Отправленные отклики"
                          aria-valuemin={0}
                          aria-valuemax={run.limit || Number(limit) || 1000}
                          aria-valuenow={run.sent || 0}
                        >
                          <div
                            style={{
                              width: `${Math.min(100, ((run.sent || 0) / (run.limit || Number(limit) || 1000)) * 100)}%`,
                            }}
                          />
                        </div>
                        <div className="progress-details">
                          <span>{num(run.processed)} обработано</span>
                          <span>{num(run.skipped)} пропущено</span>
                          <span>{num(run.total)} в подборке</span>
                        </div>
                      </div>
                      <CurrentRun state={state} />
                      <div className="run-actions">
                        {running ? (
                          <Button
                            variant="danger"
                            onClick={() => perform({ action: "stop" })}
                            disabled={
                              busy || !connected || state.phase === "stopping"
                            }
                          >
                            <Square size={16} />
                            {state.phase === "stopping"
                              ? "Останавливаем…"
                              : "Остановить запуск"}
                          </Button>
                        ) : (
                          <Button
                            onClick={() => start(true)}
                            disabled={busy || !connected}
                          >
                            <Play size={17} fill="currentColor" />
                            {authenticated
                              ? state.resume.title
                                ? "Запустить отклики"
                                : "Выбрать резюме"
                              : "Подключить hh.ru"}
                            <ArrowRight size={17} />
                          </Button>
                        )}
                        <Button
                          variant="secondary"
                          disabled={running || busy || !connected}
                          onClick={() => start(false)}
                        >
                          <Search size={16} />
                          Только найти
                        </Button>
                      </div>
                      {state.operation === "preview" &&
                        !running &&
                        (run.total || 0) > 0 && (
                          <button
                            className="text-link preview-link"
                            onClick={() => navigate("candidates")}
                          >
                            Открыть подборку · {num(run.total)} вакансий{" "}
                            <ArrowRight size={15} />
                          </button>
                        )}
                      <p className="run-footnote">
                        <ShieldCheck size={13} />
                        Письмо — только если обязательно. Повторы исключены.
                      </p>
                    </section>
                    <section className="panel rules-panel">
                      <div className="panel-title">
                        <h2>Твои правила</h2>
                        <SlidersHorizontal size={18} />
                      </div>
                      <p className="muted small">
                        Применяются перед каждым запуском
                      </p>
                      <label className="limit-label" htmlFor="limit">
                        Максимум откликов <span>за запуск</span>
                      </label>
                      <div className="limit-input">
                        <input
                          id="limit"
                          aria-label="Максимум откликов"
                          type="number"
                          min="1"
                          max="1000"
                          step="1"
                          value={limit}
                          onChange={(e) => setLimit(e.target.value)}
                          disabled={running}
                        />
                        <span>от 1 до 1 000</span>
                      </div>
                      <RuleSwitch
                        label="Без анкет"
                        description="Пропускать тесты и вопросы"
                        icon={<FileQuestion size={17} />}
                        checked={settings.skip_questionnaires}
                        disabled={running}
                        onChange={(value) =>
                          setSettings({
                            ...settings,
                            skip_questionnaires: value,
                          })
                        }
                      />
                      <RuleSwitch
                        label="В своей стране"
                        description="По стране выбранного резюме"
                        icon={<Globe2 size={17} />}
                        checked={settings.skip_foreign_vacancies}
                        disabled={running}
                        onChange={(value) =>
                          setSettings({
                            ...settings,
                            skip_foreign_vacancies: value,
                          })
                        }
                      />
                      <RuleSwitch
                        label="Спокойный темп"
                        description="Паузы 30–60 секунд"
                        icon={<Timer size={17} />}
                        checked={settings.gentle}
                        disabled={running}
                        onChange={(value) =>
                          setSettings({ ...settings, gentle: value })
                        }
                      />
                      <div className="rules-tip">
                        <Sparkles size={15} />
                        <span>
                          Спокойный темп может снизить частоту проверок, но не
                          гарантирует отсутствие капчи.
                        </span>
                      </div>
                    </section>
                  </div>
                  <section className="panel resume-strip">
                    <div className="resume-icon">
                      <FileText size={21} />
                    </div>
                    <div>
                      <span className="eyebrow">ТВОЁ РЕЗЮМЕ</span>
                      <strong>{state.resume.title}</strong>
                    </div>
                    <a
                      href={safeUrl(state.resume.url)}
                      target="_blank"
                      rel="noreferrer"
                      className="text-link"
                    >
                      Открыть на hh.ru <ArrowUpRight size={16} />
                    </a>
                    <span
                      className={cn("account-state", !authenticated && "muted")}
                    >
                      <i />
                      {authenticated ? "Аккаунт подключён" : "Нужен вход"}
                    </span>
                  </section>
                  <section className="panel history-panel">
                    <div className="panel-title">
                      <div className="inline-title">
                        <h2>Последние отклики</h2>
                        <span className="count-tag">
                          {num(state.history.total)}
                        </span>
                      </div>
                      <button
                        className="text-link"
                        onClick={() => navigate("history")}
                      >
                        Вся история <ArrowRight size={16} />
                      </button>
                    </div>
                    {state.history_error ? (
                      <div className="empty-state">{state.history_error}</div>
                    ) : (
                      <HistoryTable
                        rows={state.history.items.slice(0, 6)}
                        expanded={expanded}
                        setExpanded={setExpanded}
                      />
                    )}
                  </section>
                </>
              )}
              {(tab === "history" || tab === "candidates") && (
                <section className="panel collection-panel">
                  <div className="collection-toolbar">
                    <div className="search-input">
                      <Search size={18} />
                      <input
                        aria-label="Поиск по названию или компании"
                        placeholder="Вакансия или компания"
                        value={query}
                        onChange={(e) => {
                          setQuery(e.target.value);
                          setPage(1);
                        }}
                      />
                      {query && (
                        <button
                          className="icon-btn"
                          onClick={() => setQuery("")}
                          aria-label="Очистить поиск"
                        >
                          <X size={15} />
                        </button>
                      )}
                    </div>
                    {tab === "history" && (
                      <select
                        aria-label="Фильтр статуса"
                        value={filter}
                        onChange={(e) => {
                          setFilter(e.target.value);
                          setPage(1);
                        }}
                      >
                        <option value="">Все статусы</option>
                        <option value="sent">Отправлено</option>
                        <option value="review">Пропущено</option>
                        <option value="already">Уже есть отклик</option>
                        <option value="attention">Нужна проверка</option>
                      </select>
                    )}
                    <span className="muted small">
                      {listBusy ? (
                        <Loader2 size={17} className="spin" />
                      ) : (
                        `${num(data?.total)} записей`
                      )}
                    </span>
                  </div>
                  {listError ? (
                    <div className="banner error">{listError}</div>
                  ) : tab === "history" ? (
                    <HistoryTable
                      rows={(data?.items || []) as HistoryRow[]}
                      expanded={expanded}
                      setExpanded={setExpanded}
                    />
                  ) : (
                    <div className="candidate-grid">
                      {!data?.items.length ? (
                        <Empty
                          title="Пока нет вакансий"
                          description="Нажми «Только найти» на главном экране — здесь появится подборка."
                        />
                      ) : (
                        (data.items as Vacancy[]).map((v, i) => (
                          <article className="candidate-card" key={v.id || i}>
                            <div className="company-avatar">
                              {(v.company || "В")[0]}
                            </div>
                            <span className="muted small">
                              {v.company || "Компания не указана"}
                            </span>
                            <h3>{v.title}</h3>
                            <a
                              className="text-link"
                              href={safeUrl(v.url)}
                              target="_blank"
                              rel="noreferrer"
                            >
                              Посмотреть вакансию <ArrowUpRight size={16} />
                            </a>
                          </article>
                        ))
                      )}
                    </div>
                  )}
                  <div className="pagination">
                    <span>
                      Страница {page} из{" "}
                      {Math.max(1, Math.ceil((data?.total || 0) / 20))}
                    </span>
                    <div>
                      <Button
                        variant="secondary"
                        aria-label="Предыдущая страница"
                        disabled={page === 1 || listBusy}
                        onClick={() => setPage(page - 1)}
                      >
                        <ChevronLeft size={16} />
                      </Button>
                      <Button
                        variant="secondary"
                        aria-label="Следующая страница"
                        disabled={listBusy || page * 20 >= (data?.total || 0)}
                        onClick={() => setPage(page + 1)}
                      >
                        <ChevronRight size={16} />
                      </Button>
                    </div>
                  </div>
                </section>
              )}
              {tab === "settings" && (
                <>
                  <ProfileManager
                    state={state}
                    perform={perform}
                    prefs={{ ...settings, limit: Number(limit) || 1000 }}
                    busy={busy}
                    connected={connected}
                  />
                  <div className="settings-layout">
                    <section className="panel settings-panel">
                      <div className="panel-title">
                        <h2>Параметры запуска</h2>
                        <SlidersHorizontal size={19} />
                      </div>
                      <p className="muted">Сохраняются на этом компьютере.</p>
                      <label className="limit-label" htmlFor="settings-limit">
                        Максимум откликов
                      </label>
                      <input
                        className="text-input"
                        id="settings-limit"
                        type="number"
                        min="1"
                        max="1000"
                        value={limit}
                        disabled={running}
                        onChange={(e) => setLimit(e.target.value)}
                      />
                      <RuleSwitch
                        label="Пропускать анкеты"
                        description="Тесты и обязательные вопросы работодателя"
                        icon={<FileQuestion size={18} />}
                        checked={settings.skip_questionnaires}
                        disabled={running}
                        onChange={(v) =>
                          setSettings({ ...settings, skip_questionnaires: v })
                        }
                      />
                      <RuleSwitch
                        label="Только своя страна"
                        description="Сравнивается со страной в твоём резюме"
                        icon={<Globe2 size={18} />}
                        checked={settings.skip_foreign_vacancies}
                        disabled={running}
                        onChange={(v) =>
                          setSettings({
                            ...settings,
                            skip_foreign_vacancies: v,
                          })
                        }
                      />
                      <RuleSwitch
                        label="Спокойный темп"
                        description="Паузы 30–60 секунд между вакансиями"
                        icon={<Timer size={18} />}
                        checked={settings.gentle}
                        disabled={running}
                        onChange={(v) =>
                          setSettings({ ...settings, gentle: v })
                        }
                      />
                      <Button
                        onClick={saveSettings}
                        disabled={running || busy || !connected}
                      >
                        <Check size={16} />
                        Сохранить настройки
                      </Button>
                    </section>
                    <div className="settings-side">
                      <section className="panel">
                        <div className="panel-title">
                          <h2>Что ищем</h2>
                          <Search size={18} />
                        </div>
                        <p className="muted small">
                          Название вакансии должно соответствовать системной или
                          бизнес-аналитике.
                        </p>
                        <div className="query-chips">
                          {state.queries.map((q) => (
                            <span key={q}>{q}</span>
                          ))}
                        </div>
                      </section>
                      <section className="panel">
                        <div className="panel-title">
                          <h2>Аккаунт и резюме</h2>
                          <Link2 size={18} />
                        </div>
                        <p>
                          {state.auth.authenticated
                            ? state.auth.name
                            : "Аккаунт не подключён"}
                        </p>
                        <p className="muted small">{state.resume.title}</p>
                        <Button
                          variant="secondary"
                          disabled={running}
                          onClick={() => setLoginOpen(true)}
                        >
                          Управлять подключением <ArrowUpRight size={15} />
                        </Button>
                      </section>
                    </div>
                  </div>
                </>
              )}
              <details
                className="technical-logs"
                open={showLogs}
                onToggle={(e) => setShowLogs(e.currentTarget.open)}
              >
                <summary>
                  <Terminal size={15} />
                  Подробности запуска<span>{state.logs.length} событий</span>
                  <ChevronDown size={15} />
                </summary>
                <pre>
                  {state.logs.join("\n") ||
                    "События появятся после запуска поиска или откликов."}
                </pre>
              </details>
            </>
          )}
          <footer className="footer">
            <span>
              <span className="lime-dot" />
              Маленькие шаги. Большие возможности.
            </span>
            <span>
              Сделано для твоего следующего «да» <ArrowUpRight size={13} />
            </span>
          </footer>
        </div>
      </main>
      <Modal
        open={loginOpen}
        onOpenChange={setLoginOpen}
        title={authenticated ? "Твой аккаунт подключён" : "Залетаем в hh.ru"}
        description={
          authenticated
            ? "Авторизация хранится на этом компьютере. Пароль нам не нужен."
            : "Введи телефон или почту. Код из SMS или письма подтвердишь в панели."
        }
      >
        <form
          onSubmit={async (e: FormEvent) => {
            e.preventDefault();
            if (await perform({ action: "login", username })) {
              setLoginOpen(false);
              setUsername("");
            }
          }}
        >
          <label className="field-label" htmlFor="username">
            {authenticated
              ? "Войти заново или сменить аккаунт"
              : "Телефон или email"}
          </label>
          <input
            id="username"
            className="text-input"
            autoComplete="username"
            placeholder="+7 999 123-45-67 или email"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            disabled={running}
          />
          <Button type="submit" disabled={running || busy || !connected}>
            <ArrowRight size={17} />
            Получить код
          </Button>
        </form>
        {authenticated && (
          <div className="disconnect-box">
            <span>
              <span className="lime-dot" />
              {state?.auth.name}
            </span>
            <Button
              variant="ghost"
              disabled={running || busy}
              onClick={async () => {
                if (await perform({ action: "disconnect" }, "Аккаунт отключён"))
                  setLoginOpen(false);
              }}
            >
              <LogOut size={16} />
              Отключить
            </Button>
          </div>
        )}
        <p className="small muted modal-footnote">
          Коды вводятся только в панели и не сохраняются в журнале. Вход в
          отдельном браузере hh.ru может оставаться активным после отключения.
        </p>
      </Modal>
      <Modal
        open={helpOpen}
        onOpenChange={setHelpOpen}
        title="Всё просто. Ты управляешь."
        description="Apply работает локально и использует твой аккаунт hh.ru."
      >
        <p className="small muted">
          Авторизация и API:{" "}
          <a
            className="text-link"
            href="https://github.com/s3rgeym/hh-applicant-tool"
            target="_blank"
            rel="noreferrer"
          >
            hh-applicant-tool — Sergey M. (s3rgeym)
          </a>
          . Бесплатное приложение для личного некоммерческого использования.
        </p>
        <ol className="help-list">
          <li>
            <span>01</span>
            <div>
              <strong>Подключи аккаунт</strong>
              <p>Телефон или почта, затем код подтверждения.</p>
            </div>
          </li>
          <li>
            <span>02</span>
            <div>
              <strong>Задай свои правила</strong>
              <p>Максимум откликов и вакансии, которые стоит пропускать.</p>
            </div>
          </li>
          <li>
            <span>03</span>
            <div>
              <strong>Запусти отклики</strong>
              <p>
                «Только найти» соберёт подборку без отправки. Капча и анкеты
                появятся прямо здесь.
              </p>
            </div>
          </li>
        </ol>
        <div className="rules-tip">
          <ShieldCheck size={18} />
          <span>
            При неизвестном результате запуск остановится, чтобы не отправить
            отклик повторно. Проверь такую запись в истории и на hh.ru.
          </span>
        </div>
      </Modal>
      {toast && (
        <div className="toast" role="status">
          <CheckCircle2 size={18} />
          {toast}
          <button
            className="icon-btn"
            onClick={() => setToast("")}
            aria-label="Скрыть уведомление"
          >
            <X size={15} />
          </button>
        </div>
      )}
    </div>
  );
}
function Metric({
  label,
  value,
  icon,
  accent,
  detail,
}: {
  label: string;
  value?: number;
  icon: React.ReactNode;
  accent: string;
  detail: string;
}) {
  return (
    <div className="metric">
      <div className="metric-top">
        <span>{label}</span>
        <span className={cn("metric-icon", accent)}>{icon}</span>
      </div>
      <div className="metric-value">
        {value === undefined ? "—" : num(value)}
      </div>
      <span className="metric-detail">{detail}</span>
    </div>
  );
}
function RuleSwitch({
  label,
  description,
  icon,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  description: string;
  icon: React.ReactNode;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled: boolean;
}) {
  return (
    <div className="rule-row">
      <span className="rule-icon">{icon}</span>
      <div>
        <label>{label}</label>
        <p>{description}</p>
      </div>
      <Switch
        checked={checked}
        onCheckedChange={onChange}
        disabled={disabled}
        aria-label={label}
      />
    </div>
  );
}
function CurrentRun({ state }: { state: AppState }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!state.run.pause_until) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, [state.run.pause_until]);
  const current = state.run.current;
  const remaining = Math.max(
    0,
    Math.ceil((state.run.pause_until || 0) - now / 1000),
  );
  return (
    <div className="current-run">
      <span className={cn("current-icon", state.running && "active")}>
        {state.waiting ? (
          <Keyboard size={19} />
        ) : state.phase === "pausing" ? (
          <Timer size={19} />
        ) : state.running ? (
          <Loader2 size={19} className="spin" />
        ) : (
          <Zap size={19} />
        )}
      </span>
      <div>
        <strong>
          {state.waiting
            ? "Нужно твоё участие"
            : state.phase === "pausing"
              ? `Следующий отклик через ${remaining} с`
              : current?.title || phases[state.phase] || "Готов к запуску"}
        </strong>
        <p>
          {state.waiting
            ? "Капча или форма уже открыта выше"
            : current?.company ||
              (["completed", "stopped", "error"].includes(state.phase)
                ? state.message
                : "Вакансии по выбранному резюме и ключевым фразам")}
        </p>
      </div>
      {current?.url && (
        <a
          className="icon-btn"
          href={safeUrl(current.url)}
          target="_blank"
          rel="noreferrer"
          aria-label="Открыть текущую вакансию"
        >
          <ArrowUpRight size={18} />
        </a>
      )}
    </div>
  );
}
function Empty({
  title = "Здесь начинается твоя история",
  description = "Запусти отклики — результаты появятся здесь.",
}: {
  title?: string;
  description?: string;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">
        <FolderSearch size={26} />
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
    </div>
  );
}
function HistoryTable({
  rows,
  expanded,
  setExpanded,
}: {
  rows: HistoryRow[];
  expanded: string | null;
  setExpanded: (v: string | null) => void;
}) {
  return !rows.length ? (
    <Empty />
  ) : (
    <div className="table-scroll">
      <table className="history-table">
        <thead>
          <tr>
            <th>ВАКАНСИЯ / КОМПАНИЯ</th>
            <th>СТАТУС</th>
            <th>КОГДА</th>
            <th aria-label="Подробнее" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const status = statuses[row.status] || {
              label: row.status,
              tone: "neutral",
            };
            return (
              <HistoryRows
                key={row.vacancy_id}
                row={row}
                status={status}
                expanded={expanded === row.vacancy_id}
                toggle={() =>
                  setExpanded(
                    expanded === row.vacancy_id ? null : row.vacancy_id,
                  )
                }
              />
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
function HistoryRows({
  row,
  status,
  expanded,
  toggle,
}: {
  row: HistoryRow;
  status: { label: string; tone: string };
  expanded: boolean;
  toggle: () => void;
}) {
  return (
    <>
      <tr>
        <td>
          <div className="vacancy-cell">
            <span className="company-avatar">{(row.company || "В")[0]}</span>
            <div>
              <a href={safeUrl(row.url)} target="_blank" rel="noreferrer">
                {row.title}
                <ArrowUpRight size={12} />
              </a>
              <span>{row.company || "Компания не указана"}</span>
            </div>
          </div>
        </td>
        <td>
          <span className={cn("result-badge", status.tone)}>
            <i />
            {status.label}
          </span>
        </td>
        <td className="date-cell">{timeLabel(row.updated)}</td>
        <td>
          <button
            className={cn("icon-btn", expanded && "rotated")}
            onClick={toggle}
            aria-label={`Подробнее: ${row.title}`}
            aria-expanded={expanded}
          >
            <ChevronDown size={17} />
          </button>
        </td>
      </tr>
      {expanded && (
        <tr className="detail-row">
          <td colSpan={4}>
            {row.status === "sent"
              ? "hh.ru подтвердил доставку отклика работодателю."
              : row.note || "Дополнительной информации нет."}
          </td>
        </tr>
      )}
    </>
  );
}
function ManualCard({
  state,
  perform,
  busy,
  connected,
}: {
  state: AppState;
  perform: (v: ActionData, success?: string) => Promise<boolean>;
  busy: boolean;
  connected: boolean;
}) {
  const [text, setText] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const image = useRef<HTMLImageElement>(null);
  const auth = state.prompt_kind === "auth";
  const previousPrompt = useRef(state.prompt_id);
  useEffect(() => {
    if (previousPrompt.current !== state.prompt_id) {
      setText("");
      previousPrompt.current = state.prompt_id;
    }
    input.current?.focus();
  }, [state.prompt_id]);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    const value = text;
    if (
      await perform({
        action: auth
          ? "answer"
          : state.manual_captcha
            ? "captcha_submit"
            : "text",
        text: value,
      })
    )
      setText("");
  }
  function click(e: MouseEvent<HTMLImageElement>) {
    if (auth || busy) return;
    const rect = e.currentTarget.getBoundingClientRect();
    void perform({
      action: "click",
      x: ((e.clientX - rect.left) * e.currentTarget.naturalWidth) / rect.width,
      y: ((e.clientY - rect.top) * e.currentTarget.naturalHeight) / rect.height,
    });
  }
  return (
    <section className="panel manual-panel" aria-live="polite">
      <div className="panel-title">
        <div className="inline-title">
          <span className="attention-icon">
            <Keyboard size={19} />
          </span>
          <h2>
            {auth
              ? state.image
                ? "Минутка на капчу"
                : "Введи код — и погнали"
              : state.manual_captcha
                ? "Минутка на капчу"
                : "Нужно твоё участие"}
          </h2>
        </div>
        <span className="result-badge amber">
          <i />
          Ждём тебя
        </span>
      </div>
      <p className="muted">{state.message}</p>
      {state.image && (
        <div className={cn("browser-image-wrap", auth && "captcha-image-wrap")}>
          <img
            ref={image}
            src={`data:image/${auth ? "png" : "jpeg"};base64,${state.image}`}
            alt={
              auth
                ? "Картинка капчи hh.ru"
                : "Текущая страница hh.ru — нажимайте на поля и кнопки"
            }
            onClick={click}
            className={auth ? "captcha-image" : "browser-image"}
          />
        </div>
      )}
      {!auth && !state.manual_captcha && (
        <p className="small muted">
          Выбери поле на изображении, затем вставь текст ниже. Кнопки и варианты
          ответов на странице тоже нажимаются.
        </p>
      )}
      <form className="manual-form" onSubmit={submit}>
        <input
          ref={input}
          className="text-input"
          aria-label={
            auth
              ? state.image
                ? "Текст капчи"
                : "Код подтверждения"
              : "Текст для выбранного поля"
          }
          placeholder={
            auth
              ? state.image
                ? "Текст с картинки"
                : "Код из SMS или письма"
              : state.manual_captcha
                ? "Текст с картинки"
                : "Текст для выбранного поля"
          }
          value={text}
          onChange={(e) => setText(e.target.value)}
          autoComplete="off"
          required
          disabled={busy || !connected}
        />
        <Button type="submit" disabled={busy || !connected || !text.trim()}>
          <Send size={16} />
          {auth
            ? "Подтвердить"
            : state.manual_captcha
              ? "Отправить капчу"
              : "Вставить"}
        </Button>
        {!auth && state.manual_captcha && (
          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              setText("");
              void perform({ action: "captcha_refresh" });
            }}
            disabled={busy || !connected}
          >
            <RefreshCw size={16} />
            Другая картинка
          </Button>
        )}
      </form>
      {!auth && (
        <div className="browser-tools">
          <Button
            variant="secondary"
            onClick={() => perform({ action: "scroll", delta: -550 })}
            disabled={busy}
          >
            <ArrowUp size={15} />
            Выше
          </Button>
          <Button
            variant="secondary"
            onClick={() => perform({ action: "scroll", delta: 550 })}
            disabled={busy}
          >
            <ArrowDown size={15} />
            Ниже
          </Button>
          <Button
            variant="ghost"
            onClick={() => perform({ action: "key", key: "Tab" })}
            disabled={busy}
          >
            Tab
          </Button>
          <Button
            variant="ghost"
            onClick={() => perform({ action: "key", key: "ControlOrMeta+A" })}
            disabled={busy}
          >
            Выделить всё
          </Button>
          <Button
            variant="ghost"
            onClick={() => perform({ action: "key", key: "Backspace" })}
            disabled={busy}
          >
            Удалить
          </Button>
          {!state.manual_captcha && (
            <Button
              variant="secondary"
              onClick={() => perform({ action: "continue" })}
              disabled={busy || !connected}
            >
              <Check size={15} />
              Готово, продолжить
            </Button>
          )}
        </div>
      )}
      <p className="manual-footnote">
        <ShieldCheck size={13} />
        Ответ вводишь только ты. Мы его не сохраняем.
      </p>
    </section>
  );
}
