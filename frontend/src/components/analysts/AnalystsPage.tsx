// src/components/analysts/AnalystsPage.tsx
import {useState, type KeyboardEvent} from "react";
import type {Analyst} from "../../types/orchestrator.ts";
import {composeFeedback, newNoteId, type Note} from "../../lib/analysts.ts";
import "./AnalystsPage.css";

type Props = {
    analysts: Analyst[];
    isStreaming: boolean;
    onSubmit: (value: string) => void;
};

export function AnalystsPage({analysts, isStreaming, onSubmit}: Props) {
    const [openName, setOpenName] = useState<string | null>(null);
    const [notes, setNotes] = useState<Note[]>([]);

    const open = analysts.find(a => a.persona_name === openName) ?? null;
    const hasNotes = notes.length > 0;

    const addNote = (text: string, analyst?: string) =>
        setNotes(ns => [...ns, {id: newNoteId(), text, analyst}]);
    const removeNote = (id: string) => setNotes(ns => ns.filter(n => n.id !== id));
    const toggle = (name: string) => setOpenName(n => (n === name ? null : name));

    const submit = () => onSubmit(hasNotes ? composeFeedback(notes) : "approve");

    return (
        <div className="analysts">
            <header className="analysts__top">
                <p className="label label--italic">Journeyman</p>
                <p className="label">Chapter 1 of 4: Where</p>
                <p className="label">No. 1</p>
            </header>

            <section className="analysts__panel glass" aria-live="polite">
                {open ? (
                    <AnalystDetail
                        analyst={open}
                        onSave={(text) => addNote(text, open.persona_name)}
                        onClose={() => setOpenName(null)}
                    />
                ) : (
                    <NotesList
                        notes={notes}
                        onRemove={removeNote}
                        onClear={() => setNotes([])}
                        onOpenFirst={() => setOpenName(analysts[0]?.persona_name ?? null)}
                    />
                )}
            </section>

            <nav className="analysts__rail" aria-label="Analysts">
                {analysts.map(a => (
                    <button
                        key={a.persona_name}
                        className="chip glass"
                        aria-pressed={a.persona_name === openName}
                        onClick={() => toggle(a.persona_name)}
                    >
                        <span className="chip__name">{a.persona_name}</span>
                        <span className="chip__role">{a.focus_area}</span>
                        {notes.some(n => n.analyst === a.persona_name) &&
                            <span className="chip__dot" aria-label="has notes"/>}
                    </button>
                ))}
            </nav>

            <div className="analysts__bottom">
                <p className="label">Travel Analysts</p>
                <NoteBar
                    placeholder="Provide any general feedback for any of the analysts"
                    onAdd={(text) => addNote(text)}
                />
            </div>

            <div className="analysts__action">
                <p className="analysts__hint">
                    {hasNotes ? `${notes.length} note${notes.length > 1 ? "s" : ""}` : "Everything looks good?"}
                </p>
                <button className="analysts__submit text-button" onClick={submit} disabled={isStreaming}>
                    {hasNotes ? "Regenerate panel" : <>Next <span aria-hidden>→</span></>}
                </button>
            </div>
        </div>
    );
}

/* ---------- Open analyst (frames: Page 1 / Page 2) ---------- */
function AnalystDetail({analyst, onSave, onClose}: {
    analyst: Analyst;
    onSave: (text: string) => void;
    onClose: () => void;
}) {
    const [draft, setDraft] = useState("");
    const save = () => {
        if (!draft.trim()) return;
        onSave(draft.trim());
        setDraft("");
    };

    return (
        <article className="analyst">
            <h2 className="analyst__name">{analyst.persona_name}</h2>
            <p className="analyst__role">{analyst.focus_area}</p>
            <p className="analyst__body">{analyst.description}</p>
            {/*{analyst.affiliation && <p className="analyst__meta">{analyst.affiliation}</p>}*/}

            <label className="analyst__note">
                <span className="analyst__note-label">Feedback for {analyst.persona_name}</span>
                <textarea
                    className="analyst__textarea glass"
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    placeholder="e.g. Don't push surf days if the spots are out of the way"
                    rows={4}
                />
            </label>

            <div className="analyst__actions">
                <button className="pill" onClick={save}>Save</button>
                <button className="pill" onClick={onClose}>Cancel</button>
            </div>
        </article>
    );
}

/* ---------- Notes list (frames: Page 3 / Page 4) ---------- */
function NotesList({notes, onRemove, onClear, onOpenFirst}: {
    notes: Note[];
    onRemove: (id: string) => void;
    onClear: () => void;
    onOpenFirst: () => void;
}) {
    return (
        <div className="notes">
            <h2 className="notes__title">Feedback</h2>

            {notes.length === 0 ? (
                <button className="notes__empty text-button" onClick={onOpenFirst}>
                    Click to open an analyst <span aria-hidden>→</span>
                </button>
            ) : (
                <ol className="notes__list">
                    {notes.map(n => (
                        <li key={n.id} className="notes__item glass">
                            <span>
                                {n.analyst && <strong className="notes__tag">{n.analyst} · </strong>}
                                {n.text}
                            </span>
                            <button className="notes__remove text-button" aria-label="Remove note"
                                    onClick={() => onRemove(n.id)}>×
                            </button>
                        </li>
                    ))}
                </ol>
            )}

            {notes.length > 0 && <button className="pill notes__clear" onClick={onClear}>Clear</button>}
        </div>
    );
}

/* ---------- Bottom input: Enter adds, Shift+Enter = new line ---------- */
function NoteBar({placeholder, onAdd}: { placeholder: string; onAdd: (text: string) => void }) {
    const [value, setValue] = useState("");

    const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
        // isComposing: don't submit mid-word when typing Chinese/Japanese/Korean
        if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            if (!value.trim()) return;
            onAdd(value.trim());
            setValue("");
        }
    };

    return (
        <div className="note-bar glass">
            <textarea
                className="note-bar__input"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder={placeholder}
                rows={1}
                aria-label="General feedback"
            />
            <span className="note-bar__hint" aria-hidden>↵</span>
        </div>
    );
}