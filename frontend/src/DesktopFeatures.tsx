import { useEffect, useState } from "react";
import {
  ArrowRight,
  FileText,
  Plus,
  RefreshCw,
  Save,
  Timer,
  ShieldCheck,
} from "lucide-react";
import { Button } from "./components/ui";
import type { ActionData, AppState, Preferences } from "./types";

type Perform = (data: ActionData, success?: string) => Promise<boolean>;
type Profile = {
  id: string;
  name: string;
  resume_id: string;
  resume_title: string;
  queries: string[];
  search_mode: string;
  letter_mode: string;
  letter_text: string;
};
const initialLetter =
  "Здравствуйте! Хочу откликнуться на вакансию «{vacancy}» в {company}. Буду рад обсудить, как мой опыт может быть полезен вашей команде.";
const blank = {
  id: "",
  name: "",
  resume_id: "",
  resume_title: "",
  queries: [] as string[],
  search_mode: "resume",
  letter_mode: "required",
  letter_text: initialLetter,
};

export function ProfileBar({
  state,
  perform,
  configure,
}: {
  state: AppState;
  perform: Perform;
  configure: () => void;
}) {
  const profiles = state.profiles?.items || [];
  return (
    <section className="panel profile-bar">
      <div className="resume-icon">
        <FileText size={20} />
      </div>
      <div>
        <span className="eyebrow">ПРОФИЛЬ ПОИСКА</span>
        {profiles.length ? (
          <select
            aria-label="Активный профиль"
            value={state.profiles?.selected || ""}
            disabled={state.running}
            onChange={(e) =>
              perform({ action: "select_profile", profile_id: e.target.value })
            }
          >
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        ) : (
          <strong>Выбери резюме, с которого начнём</strong>
        )}
      </div>
      <button className="text-link" onClick={configure}>
        Настроить профиль <ArrowRight size={16} />
      </button>
    </section>
  );
}

export function ProfileManager({
  state,
  perform,
  prefs,
  busy,
  connected,
}: {
  state: AppState;
  perform: Perform;
  prefs: Preferences;
  busy: boolean;
  connected: boolean;
}) {
  const [draft, setDraft] = useState<Profile>(blank),
    [fresh, setFresh] = useState(false),
    [query, setQuery] = useState("");
  const selected = (state.profiles?.items || []).find(
    (p) => p.id === state.profiles?.selected,
  );
  const key = JSON.stringify(selected);
  useEffect(() => {
    if (selected && !fresh) {
      setDraft(selected);
      setQuery(selected.queries.join("\n"));
    }
  }, [key, fresh]);
  const resumes = state.resumes || [];
  function choose(id: string) {
    const r = resumes.find((r) => r.id === id);
    if (r) {
      setDraft({
        ...draft,
        resume_id: r.id,
        resume_title: r.title,
        name: draft.name || r.title,
      });
      setQuery(r.title.replace(/\s*\(.*/, ""));
    }
  }
  function create() {
    setFresh(true);
    setDraft(blank);
    setQuery("");
  }
  async function save() {
    if (
      await perform(
        {
          action: "save_profile",
          profile_id: draft.id,
          profile_name: draft.name,
          resume_id: draft.resume_id,
          queries: query.split("\n"),
          search_mode: draft.search_mode,
          letter_mode: draft.letter_mode,
          letter_text: draft.letter_text,
          ...prefs,
        },
        "Профиль и письмо сохранены",
      )
    )
      setFresh(false);
  }
  const disabled = state.running || busy || !connected;
  const preview = draft.letter_text
    .replaceAll("{vacancy}", draft.resume_title || "Название вакансии")
    .replaceAll("{company}", "Название компании")
    .replaceAll("{resume}", draft.resume_title || "Название резюме");
  return (
    <section className="panel profile-editor">
      <div className="panel-title">
        <h2>Резюме, поиск и письмо</h2>
        <Button variant="secondary" onClick={create} disabled={disabled}>
          <Plus size={15} />
          Новый профиль
        </Button>
      </div>
      <p className="muted small">
        Каждому резюме — свои направления поиска и шаблон. История откликов
        разделена по резюме.
      </p>
      <div className="editor-grid">
        <div>
          <label className="field-label" htmlFor="profile-name">
            Название профиля
          </label>
          <input
            id="profile-name"
            className="text-input"
            value={draft.name}
            placeholder="Например: системная аналитика"
            disabled={disabled}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          />
          <div className="field-label inline-label">
            <label htmlFor="profile-resume">Резюме hh.ru</label>
            <button
              className="text-link"
              disabled={disabled || !state.auth.authenticated}
              onClick={() => perform({ action: "load_resumes" })}
            >
              <RefreshCw size={13} />
              Загрузить резюме
            </button>
          </div>
          <select
            className="text-input"
            id="profile-resume"
            value={draft.resume_id}
            disabled={disabled}
            onChange={(e) => choose(e.target.value)}
          >
            <option value="">Выбери резюме из аккаунта</option>
            {draft.resume_id &&
              !resumes.some((r) => r.id === draft.resume_id) && (
                <option value={draft.resume_id}>{draft.resume_title}</option>
              )}
            {resumes.map((r) => (
              <option key={r.id} value={r.id}>
                {r.title}
              </option>
            ))}
          </select>
          <label className="field-label" htmlFor="profile-mode">
            Как искать вакансии
          </label>
          <select
            id="profile-mode"
            className="text-input"
            value={draft.search_mode}
            disabled={disabled}
            onChange={(e) =>
              setDraft({ ...draft, search_mode: e.target.value })
            }
          >
            <option value="resume">Рекомендации hh.ru по резюме</option>
            <option value="keywords">По ключевым фразам</option>
          </select>
          <label className="field-label" htmlFor="profile-queries">
            Фильтр названий вакансий
          </label>
          <textarea
            id="profile-queries"
            className="text-input"
            rows={4}
            disabled={disabled}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Одна фраза на строку"
          />
          <p className="small muted">
            Например, «системный аналитик». Рекомендации дополнительно
            фильтруются по этим фразам — без оценки всех требований вакансии.
          </p>
        </div>
        <div>
          <label className="field-label" htmlFor="letter-mode">
            Сопроводительное письмо
          </label>
          <select
            id="letter-mode"
            className="text-input"
            value={draft.letter_mode}
            disabled={disabled}
            onChange={(e) =>
              setDraft({ ...draft, letter_mode: e.target.value })
            }
          >
            <option value="required">Только когда обязательно</option>
            <option value="always">
              С каждым откликом, если форма позволяет
            </option>
            <option value="none">Не добавлять</option>
          </select>
          <label className="field-label" htmlFor="letter-text">
            Шаблон письма
          </label>
          <textarea
            id="letter-text"
            className="text-input"
            rows={8}
            value={draft.letter_text}
            disabled={disabled}
            onChange={(e) =>
              setDraft({ ...draft, letter_text: e.target.value })
            }
          />
          <div className="template-tags">
            {["{vacancy}", "{company}", "{resume}"].map((tag) => (
              <button
                type="button"
                key={tag}
                disabled={disabled}
                onClick={() =>
                  setDraft({
                    ...draft,
                    letter_text: draft.letter_text + " " + tag,
                  })
                }
              >
                {tag}
              </button>
            ))}
          </div>
          <span className="field-label">Предпросмотр подстановок</span>
          <div className="letter-preview">
            {draft.letter_mode === "none"
              ? "Письмо не добавляется. Вакансии с обязательным письмом будут пропущены."
              : preview || "Здесь появится текст письма."}
          </div>
        </div>
      </div>
      <Button onClick={save} disabled={disabled || !draft.resume_id}>
        <Save size={16} />
        Сохранить профиль и письмо
      </Button>
    </section>
  );
}

export function QueueCard({
  state,
  perform,
  busy,
}: {
  state: AppState;
  perform: Perform;
  busy: boolean;
}) {
  const q = state.queue;
  if (!q || state.running || q.remaining === 0 || q.sent >= q.max_count)
    return null;
  return (
    <section className="panel queue-card">
      <div>
        <strong>Есть сохранённая очередь</strong>
        <p>
          {q.sent} отправлено · {q.remaining} осталось
          {q.attention ? ` · ${q.attention} требуют проверки` : ""}
        </p>
        <p className="small muted">
          Неподтверждённые отклики не повторятся. Продолжение использует
          параметры и письмо сохранённой очереди.
        </p>
      </div>
      <Button
        disabled={busy || !state.auth.authenticated}
        onClick={() => perform({ action: "resume_queue", queue_id: q.id })}
      >
        Продолжить очередь <ArrowRight size={16} />
      </Button>
    </section>
  );
}

export function CaptchaWait({
  state,
  perform,
  busy,
}: {
  state: AppState;
  perform: Perform;
  busy: boolean;
}) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  const remaining = Math.max(
    0,
    Math.ceil((state.run.pause_until || 0) - now / 1000),
  );
  return (
    <section className="panel captcha-wait">
      <Timer size={24} />
      <div>
        <strong>Капча: пауза {state.run.captcha_attempt || 1} из 2</strong>
        <p>
          Следующая проверка через {Math.floor(remaining / 60)}:
          {String(remaining % 60).padStart(2, "0")}. После двух неудачных
          проверок попросим ввести текст вручную.
        </p>
        <p className="small muted">
          <ShieldCheck size={12} /> Исходный отклик повторяется только после
          явного отказа, а не при неизвестном результате.
        </p>
      </div>
      <Button
        variant="secondary"
        disabled={busy}
        onClick={() => perform({ action: "captcha_now" })}
      >
        Заполнить сейчас
      </Button>
    </section>
  );
}
