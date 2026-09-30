"use client";

import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";

type Estimate = { price_min: number; price_max: number; confidence: string; demo: boolean; items: { name: string; min: number; max: number }[] };
type Slot = { id: number; start_at: string };
type ChatMessage = { role: "assistant" | "user"; text: string; choices?: string[] };
type ApiReply = { session_id?: string; assistant_message?: string; quick_replies?: string[]; next_action?: string; estimate?: Estimate; stage?: string };

const money = (n: number) => new Intl.NumberFormat("ru-RU").format(n);
const prettifyDate = (value: string) => new Intl.DateTimeFormat("ru-RU", { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" }).format(new Date(value));

export default function Home() {
  const [started, setStarted] = useState(false);
  const [company, setCompany] = useState({ company_name: "Тёплый балкон", city: "Уфа" });
  const [session, setSession] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [handoff, setHandoff] = useState(false);
  const [photoCount, setPhotoCount] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [contact, setContact] = useState({ name: "", phone: "", address: "" });
  const [consent, setConsent] = useState(false);
  const [slots, setSlots] = useState<Slot[]>([]);
  const [leadCreated, setLeadCreated] = useState(false);
  const [complete, setComplete] = useState(false);
  const [selectedSlot, setSelectedSlot] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const landingLogged = useRef(false);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, busy]);
  useEffect(() => {
    if (landingLogged.current) return;
    landingLogged.current = true;
    fetch("/api/health").then((response) => response.json()).then((data) => setCompany(data.company)).catch(() => {});
    fetch("/api/events", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: "landing_opened", channel: "web" }), keepalive: true }).catch(() => {});
  }, []);
  useEffect(() => {
    if (!session) return;
    const onHide = () => fetch("/api/events", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: "session_abandoned", channel: "web", session_id: session }), keepalive: true }).catch(() => {});
    window.addEventListener("pagehide", onHide);
    return () => window.removeEventListener("pagehide", onHide);
  }, [session]);

  async function start() {
    setBusy(true); setError("");
    const params = new URLSearchParams(window.location.search);
    const utm = Object.fromEntries(["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"].flatMap((key) => params.has(key) ? [[key, params.get(key)!]] : []));
    try {
      const response = await fetch("/api/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ channel: "web", utm }) });
      if (!response.ok) throw new Error("Не удалось начать расчёт. Попробуйте ещё раз.");
      const data: ApiReply = await response.json();
      setSession(data.session_id || ""); setStarted(true);
      setMessages([{ role: "assistant", text: data.assistant_message || "Расскажите, что хотите сделать?", choices: ["Застеклить", "Заменить старое остекление", "Утеплить", "Сделать под ключ", "Пока не знаю"] }]);
    } catch (e) { setError(e instanceof Error ? e.message : "Ошибка соединения"); }
    finally { setBusy(false); }
  }

  async function send(text = input) {
    const clean = text.trim(); if (!clean || !session || busy) return;
    setInput(""); setError(""); setMessages((old) => [...old, { role: "user", text: clean }]); setBusy(true);
    try {
      const response = await fetch(`/api/sessions/${session}/messages`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: clean }) });
      const data: ApiReply = await response.json();
      if (!response.ok) throw new Error((data as unknown as { detail?: string }).detail || "Не удалось отправить ответ");
      setMessages((old) => [...old, { role: "assistant", text: data.assistant_message || "Продолжим.", choices: data.quick_replies }]);
      if (data.estimate) setEstimate(data.estimate);
      if (data.next_action === "request_contact") setHandoff(true);
    } catch (e) { setError(e instanceof Error ? e.message : "Ошибка соединения"); }
    finally { setBusy(false); }
  }

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files || []); if (!files.length || !session) return;
    setError(""); setBusy(true);
    const form = new FormData(); files.forEach((file) => form.append("files", file));
    try {
      const response = await fetch(`/api/sessions/${session}/photos`, { method: "POST", body: form });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Не удалось загрузить фото");
      setPhotoCount(data.count);
      setMessages((old) => [...old, { role: "assistant", text: data.assistant_message || "Фото получили. Спасибо!" }]);
    } catch (e) { setError(e instanceof Error ? e.message : "Ошибка загрузки"); }
    finally { setBusy(false); if (fileRef.current) fileRef.current.value = ""; }
  }

  async function submitContact(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const response = await fetch(`/api/sessions/${session}/contact`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...contact, consent }) });
      const data = await response.json(); if (!response.ok) throw new Error(data.detail || "Проверьте данные");
      setLeadCreated(true);
      if (data.next_action === "handoff") { setComplete(true); setMessages((old) => [...old, { role: "assistant", text: data.assistant_message }]); return; }
      const result = await fetch(`/api/sessions/${session}/slots`); setSlots(await result.json());
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось сохранить контакт"); }
    finally { setBusy(false); }
  }

  async function book() {
    if (!selectedSlot) return; setBusy(true); setError("");
    try {
      const response = await fetch(`/api/sessions/${session}/book`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ slot_id: selectedSlot }) });
      const data = await response.json(); if (!response.ok) throw new Error(data.detail || "Слот уже занят. Обновите страницу и выберите другой.");
      setComplete(true); setMessages((old) => [...old, { role: "assistant", text: data.assistant_message || "Готово! Замер запланирован." }]);
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось забронировать время"); }
    finally { setBusy(false); }
  }

  return <main>
    <header className="topbar"><a className="brand" href="#top"><span className="brand-mark">{company.company_name.slice(0,1)}</span><span>{company.company_name}</span></a><div className="top-meta"><span className="online-dot" />Работаем в {company.city}</div><a className="phone" href="#top">Бесплатный замер</a></header>
    {!started ? <section className="hero" id="top">
      <div className="hero-copy"><span className="eyebrow">Остекление и отделка в Уфе</span><h1>Балкон, в котором<br /><em>хочется остаться</em></h1><p className="hero-lede">Ответьте на несколько вопросов — подскажем подходящий вариант и назовём предварительную стоимость.</p><div className="hero-actions"><button className="primary" onClick={start} disabled={busy}>Рассчитать стоимость <span>→</span></button><span className="microcopy">Бесплатно · без регистрации · 3–5 минут</span></div><div className="trust-row"><span>✳ Замер бесплатный</span><span>✳ Можно без фото</span><span>✳ Без обязательств</span></div></div>
      <div className="hero-visual"><div className="sun"/><div className="room"><div className="window"><div/><div/><div/></div><div className="plant">✳</div><div className="seat"/><div className="visual-note"><span>⌁</span><div><b>Подберём решение</b><small>для вашего пространства</small></div></div></div><div className="visual-tag">Тепло начинается<br />с хороших окон</div></div>
    </section> : <section className="chat-shell"><div className="chat-heading"><div><span className="eyebrow">ПОДБОР РЕШЕНИЯ</span><h2>Давайте разберёмся</h2></div><span className="step-pill"><span className="online-dot"/> Можно отвечать своими словами</span></div><div className="chat-window">
      <div className="messages">{messages.map((message,index)=><div className={`message-row ${message.role}`} key={index}><div className="avatar">{message.role==="assistant"?"Т":"Вы"}</div><div className="message-content"><div className="bubble">{message.text}</div>{message.choices?.length ? <div className="quick-replies">{message.choices.map((choice)=><button key={choice} onClick={()=>choice==="Добавить фото"?fileRef.current?.click():send(choice)} disabled={busy}>{choice}</button>)}</div>:null}</div></div>)}{busy&&<div className="message-row assistant"><div className="avatar">Т</div><div className="bubble typing"><i/><i/><i/></div></div>}
      {estimate && <div className="estimate-card"><div className="estimate-top"><span className="eyebrow">ПРЕДВАРИТЕЛЬНЫЙ ВАРИАНТ</span>{estimate.demo&&<span className="demo-badge">Демо-расчёт</span>}</div><h3>{valueLabel(estimate)}</h3><div className="price-range">{money(estimate.price_min)}–{money(estimate.price_max)} <span>₽</span></div><ul>{estimate.items.map((item)=><li key={item.name}><span>{item.name}</span><span>{money(item.min)}–{money(item.max)} ₽</span></li>)}</ul><p>Точную стоимость специалист определит после замера. Расчёт предварительный.</p></div>}
      {(estimate||handoff) && !leadCreated && <form className="contact-card" onSubmit={submitContact}><span className="eyebrow">{handoff?"СВЯЗЬ СО СПЕЦИАЛИСТОМ":"СЛЕДУЮЩИЙ ШАГ"}</span><h3>{handoff?"Передать заявку специалисту":"Запишем на бесплатный замер"}</h3><p>Оставьте контакты — {handoff?"специалист свяжется с вами.":"покажем свободное время специалиста."}</p><label>Как к вам обращаться<input required minLength={2} value={contact.name} onChange={(e)=>setContact({...contact,name:e.target.value})} placeholder="Ваше имя" autoComplete="name"/></label><label>Номер телефона<input required type="tel" value={contact.phone} onChange={(e)=>setContact({...contact,phone:e.target.value})} placeholder="+7 (___) ___-__-__" autoComplete="tel"/></label><label>Адрес замера<input required value={contact.address} onChange={(e)=>setContact({...contact,address:e.target.value})} placeholder="Уфа, улица, дом" autoComplete="street-address"/></label><label className="consent"><input type="checkbox" checked={consent} onChange={(e)=>setConsent(e.target.checked)}/><span>Согласен(на) на обработку персональных данных по <a href="/privacy" target="_blank">условиям согласия</a></span></label><button className="primary" disabled={busy||!consent}>{busy?"Сохраняем…":handoff?"Передать заявку →":"Показать свободное время →"}</button></form>}
      {leadCreated && !complete && <div className="slots-card"><span className="eyebrow">ВЫБЕРИТЕ ВРЕМЯ</span><h3>Когда вам удобно?</h3>{slots.length ? <div className="slot-grid">{slots.map((slot)=><button className={selectedSlot===slot.id?"selected":""} key={slot.id} onClick={()=>setSelectedSlot(slot.id)}>{prettifyDate(slot.start_at)}</button>)}</div>:<p>Свободных слотов сейчас нет. Оставили заявку — специалист свяжется с вами.</p>}{selectedSlot&&<button className="primary" onClick={book} disabled={busy}>Записаться на это время →</button>}</div>}
      {complete&&<div className="success-card"><div className="success-icon">✓</div><h3>{handoff&&!leadCreated?"Заявка у специалиста":"Всё готово!"}</h3><p>{handoff&&!leadCreated?"Специалист свяжется с вами по телефону.":handoff?"Передал заявку специалисту. Он свяжется с вами.":"Замер запланирован. Скоро подтвердим запись по телефону."}</p></div>}
      {error&&<div className="error-box" role="alert">{error}</div>}{!estimate&&session&&<div className="upload-line"><input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp,image/heic" multiple hidden onChange={upload}/><button onClick={()=>fileRef.current?.click()} disabled={busy}>＋ Добавить фото {photoCount>0?`(${photoCount})`:""}</button><span>До 4 фото · можно продолжить без них</span></div>}
      {!estimate&&session&&<form className="composer" onSubmit={(e)=>{e.preventDefault();send();}}><input value={input} onChange={(e)=>setInput(e.target.value)} placeholder="Напишите сообщение…" aria-label="Ваше сообщение"/><button aria-label="Отправить" disabled={!input.trim()||busy}>↑</button></form>}<div ref={bottomRef}/></div><div className="chat-foot"><span>Предварительная стоимость — ориентир, не оферта.</span><span>Фото не заменяют профессиональный замер.</span></div></div></section>}
    <footer className="footer"><span>© 2026 Тёплый балкон</span><a href="/privacy">Конфиденциальность</a><span>Расчёт ориентировочный. Точную стоимость определит специалист.</span></footer>
    <noscript>Для работы расчёта включите JavaScript.</noscript>
  </main>;
}

function valueLabel(estimate: Estimate) {
  const names = estimate.items.map((item) => item.name);
  return names.length ? names.slice(0,2).join(" · ") : "Остекление балкона";
}
