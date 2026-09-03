"use client";

import { useState, useRef, useEffect, useCallback } from "react";

// ============ Types ============
interface UIAction {
  type: "FORM" | "PROGRESS_BAR" | "LOG_VIEW" | "DIFF_TABLE" | "SINGLE_SELECT_CONFIRM";
  title: string;
  message?: string;
  phase?: string;
  [key: string]: unknown;
}

interface Message {
  id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  toolName?: string;
  toolResult?: unknown;
  uiAction?: UIAction;
  timestamp: number;
}

interface StreamEvent {
  type: "content" | "tool_call" | "tool_result" | "ui_action" | "done";
  content?: string;
  tool_name?: string;
  result?: unknown;
  ui_action?: UIAction;
  session_id?: string;
}

interface SidebarItem {
  id: string;
  label: string;
  icon: string;
  active?: boolean;
}

// ============ Icons ============
const Icons = {
  send: () => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>,
  sparkles: () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/></svg>,
  database: () => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12v14"/></svg>,
  workflow: () => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="5" cy="12" r="3"/><circle cx="19" cy="12" r="3"/><circle cx="12" cy="5" r="3"/><circle cx="12" cy="19" r="3"/><path d="M7.5 10.5 12 9l4.5 1.5M7.5 13.5 12 15l4.5-1.5"/></svg>,
  chat: () => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>,
  activity: () => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>,
  check: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>,
  x: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>,
  loader: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="animate-spin"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>,
  copy: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>,
  menu: () => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></svg>,
  arrow: () => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5v14M5 12l7 7 7-7"/></svg>,
  search: () => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>,
};

// ============ Sample Prompts ============
const SAMPLE_PROMPTS = [
  { icon: <Icons.database />, text: "把 HIS 的门诊记录同步到 OMOP Drug Exposure 表", color: "#6366f1" },
  { icon: <Icons.search />, text: "帮我搜索 Datahub 中 HIS 相关的表结构", color: "#8b5cf6" },
  { icon: <Icons.activity />, text: "查询术语「二甲双胍」的 OMOP 标准映射", color: "#0ea5e9" },
  { icon: <Icons.workflow />, text: "查看 Argo 工作流 omop-sync 的运行状态", color: "#22c55e" },
];

// ============ Tool Icons Map ============
const TOOL_ICONS: Record<string, { icon: React.ReactNode; color: string }> = {
  ingestion_submit: { icon: <Icons.database />, color: "#6366f1" },
  terminology_match: { icon: <Icons.activity />, color: "#8b5cf6" },
  workflow_status: { icon: <Icons.workflow />, color: "#22c55e" },
  datahub_search: { icon: <Icons.search />, color: "#0ea5e9" },
  doris_query: { icon: <Icons.chat />, color: "#f59e0b" },
};

// ============ Progress Bar Component ============
function ProgressBar({ title, phase, message }: { title: string; phase: string; message: string }) {
  const pct = phase === "Succeeded" ? 100 : phase === "Failed" ? 100 : phase === "Running" || phase === "Pending" ? 60 : 30;
  const colorClass = phase === "Succeeded" ? "bg-green-500" : phase === "Failed" ? "bg-red-500" : "bg-gradient-to-r from-indigo-500 to-purple-500";
  const statusColor = phase === "Succeeded" ? "text-green-400" : phase === "Failed" ? "text-red-400" : "text-indigo-400";

  return (
    <div className="animate-fade-in rounded-xl p-5 border border-zinc-800 bg-gradient-to-br from-zinc-900/80 to-zinc-900/40 backdrop-blur-sm">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-zinc-200">{title}</span>
        </div>
        <span className={`text-xs font-medium px-2.5 py-1 rounded-full border ${
          phase === "Succeeded" ? "bg-green-500/10 border-green-500/30 text-green-400" :
          phase === "Failed" ? "bg-red-500/10 border-red-500/30 text-red-400" :
          "bg-indigo-500/10 border-indigo-500/30 text-indigo-400"
        }`}>
          {phase}
        </span>
      </div>
      <div className="h-2.5 progress-track mb-3">
        <div className={`h-full ${colorClass} progress-fill`} style={{ width: `${pct}%` }} />
      </div>
      <p className="text-xs text-zinc-500">{message}</p>
    </div>
  );
}

// ============ Confirm Dialog Component ============
function ConfirmDialog({
  title, term, candidates, message, onConfirm
}: {
  title: string; term: string;
  candidates: Array<{omop_concept_id: number; concept_name: string; confidence: number}>;
  message: string; onConfirm: (id: number) => void;
}) {
  const [selected, setSelected] = useState<number | null>(null);

  return (
    <div className="animate-fade-in rounded-xl border border-zinc-800 bg-zinc-900/80 backdrop-blur-sm p-5">
      <div className="flex items-center gap-2 mb-1">
        <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-purple-500/10 border border-purple-500/30 text-purple-400">需要确认</span>
      </div>
      <h3 className="text-sm font-semibold text-zinc-100 mt-3 mb-1">{title}</h3>
      <p className="text-xs text-zinc-400 mb-4">术语「<span className="text-purple-300">{term}</span>」匹配结果：{message}</p>
      <div className="space-y-2 mb-5">
        {candidates.map((c) => (
          <button key={c.omop_concept_id}
            onClick={() => setSelected(c.omop_concept_id)}
            className={`w-full flex items-center gap-3 p-3 rounded-lg border transition-all text-left ${
              selected === c.omop_concept_id
                ? "border-purple-500/50 bg-purple-500/10"
                : "border-zinc-800 bg-zinc-800/50 hover:border-zinc-700"
            }`}>
            <div className={`w-4 h-4 rounded-full border-2 flex-shrink-0 transition-all ${
              selected === c.omop_concept_id ? "border-purple-500 bg-purple-500" : "border-zinc-600"
            }`}>
              {selected === c.omop_concept_id && <div className="w-full h-full flex items-center justify-center"><Icons.check /></div>}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm text-zinc-200 truncate">{c.concept_name}</div>
              <div className="text-xs text-zinc-500">#{c.omop_concept_id}</div>
            </div>
            <span className={`text-xs font-medium flex-shrink-0 ${
              c.confidence > 0.85 ? "text-green-400" : "text-yellow-400"
            }`}>
              {Math.round(c.confidence * 100)}%
            </span>
          </button>
        ))}
      </div>
      <button onClick={() => selected && onConfirm(selected)}
        disabled={!selected}
        className="w-full py-2.5 rounded-lg bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 disabled:opacity-40 disabled:cursor-not-allowed text-sm font-medium text-white transition-all">
        确认映射
      </button>
    </div>
  );
}

// ============ Tool Result Card ============
function ToolResultCard({ toolName, result }: { toolName: string; result: unknown }) {
  const [expanded, setExpanded] = useState(false);
  const tool = TOOL_ICONS[toolName];

  return (
    <div className="mt-3 rounded-lg border border-zinc-800 bg-zinc-900/50 overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-4 py-2.5 hover:bg-zinc-800/50 transition-colors">
        <span style={{ color: tool?.color }}>{tool?.icon}</span>
        <span className="text-xs font-medium text-zinc-400">调用工具: <span style={{ color: tool?.color }}>{toolName}</span></span>
        <span className="ml-auto text-zinc-600">{expanded ? "收起" : "展开"}</span>
      </button>
      {expanded && (
        <div className="px-4 pb-3">
          <pre className="text-xs text-zinc-500 font-mono whitespace-pre-wrap bg-zinc-950 rounded-lg p-3 overflow-x-auto">
            {JSON.stringify(result, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

// ============ Empty State ============
function EmptyState({ onSelect }: { onSelect: (q: string) => void }) {
  return (
    <div className="flex flex-col items-center justify-center min-h-[70vh] px-4 animate-fade-in">
      {/* Logo */}
      <div className="relative mb-6 animate-float">
        <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-indigo-600 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
          <span className="text-3xl">🏥</span>
        </div>
        <div className="absolute -inset-1 rounded-2xl bg-gradient-to-br from-indigo-600/30 to-purple-600/30 blur-lg -z-10" />
      </div>

      {/* Title */}
      <h2 className="text-xl font-bold text-zinc-100 mb-1 text-center">
        OMOP <span className="gradient-text">医疗数据治理平台</span>
      </h2>
      <p className="text-sm text-zinc-500 mb-8 text-center max-w-md">
        AI 驱动的医疗数据标准化底座，自动将医院异构数据转换为 OMOP CDM 标准模型
      </p>

      {/* Capabilities */}
      <div className="grid grid-cols-2 gap-3 mb-8 max-w-lg w-full">
        {[
          { icon: <Icons.database />, label: "数据同步", desc: "SeaTunnel + Argo", color: "#6366f1" },
          { icon: <Icons.activity />, label: "术语映射", desc: "pgvector 语义匹配", color: "#8b5cf6" },
          { icon: <Icons.search />, label: "元数据查询", desc: "Datahub 资产全景", color: "#0ea5e9" },
          { icon: <Icons.workflow />, label: "任务监控", desc: "Argo Workflows", color: "#22c55e" },
        ].map((cap) => (
          <div key={cap.label} className="flex items-center gap-3 p-3 rounded-xl border border-zinc-800 bg-zinc-900/50 backdrop-blur-sm">
            <div className="w-9 h-9 rounded-lg flex items-center justify-center" style={{ backgroundColor: `${cap.color}15`, color: cap.color }}>
              {cap.icon}
            </div>
            <div>
              <div className="text-sm font-medium text-zinc-200">{cap.label}</div>
              <div className="text-xs text-zinc-500">{cap.desc}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Sample prompts */}
      <div className="max-w-lg w-full">
        <p className="text-xs text-zinc-600 mb-3 text-center">试试这些指令</p>
        <div className="space-y-2">
          {SAMPLE_PROMPTS.map((p, i) => (
            <button key={i}
              onClick={() => onSelect(p.text)}
              className="w-full flex items-center gap-3 px-4 py-3 rounded-xl border border-zinc-800 bg-zinc-900/50 hover:bg-zinc-800/60 hover:border-zinc-700 transition-all text-left group">
              <span style={{ color: p.color }}>{p.icon}</span>
              <span className="text-sm text-zinc-400 group-hover:text-zinc-200 flex-1">{p.text}</span>
              <span className="text-zinc-600 opacity-0 group-hover:opacity-100 transition-opacity"><Icons.arrow /></span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ============ Typing Indicator ============
function TypingIndicator() {
  return (
    <div className="flex items-start gap-3 animate-fade-in">
      <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-600 to-purple-600 flex items-center justify-center flex-shrink-0 text-sm">AI</div>
      <div className="px-4 py-3 rounded-2xl rounded-tl-sm bg-zinc-900 border border-zinc-800">
        <div className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full bg-zinc-600 animate-typing" />
          <span className="w-2 h-2 rounded-full bg-zinc-600 animate-typing" />
          <span className="w-2 h-2 rounded-full bg-zinc-600 animate-typing" />
        </div>
      </div>
    </div>
  );
}

// ============ Message Bubble ============
function MessageBubble({ msg, onCopy }: { msg: Message; onCopy: (id: string) => void }) {
  const isUser = msg.role === "user";
  const isTool = msg.role === "tool";
  const tool = msg.toolName ? TOOL_ICONS[msg.toolName] : null;

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} animate-fade-in`}>
      <div className={`max-w-[75%] ${isUser ? "order-2" : "order-1"}`}>
        {/* User message */}
        {isUser && (
          <div className="msg-user px-4 py-3 rounded-2xl rounded-tr-sm bg-gradient-to-br from-indigo-600 to-purple-600 text-white text-sm leading-relaxed">
            {msg.content}
          </div>
        )}

        {/* Assistant message */}
        {!isUser && !isTool && (
          <div className="msg-assistant">
            <div className="flex items-start gap-3">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-600 to-purple-600 flex items-center justify-center flex-shrink-0 text-sm font-bold text-white">AI</div>
              <div className="flex-1 min-w-0">
                <div className="px-4 py-3 rounded-2xl rounded-tl-sm bg-zinc-900 border border-zinc-800 text-sm text-zinc-200 leading-relaxed whitespace-pre-wrap">
                  {msg.content}
                </div>
                <div className="flex items-center gap-2 mt-2">
                  <button onClick={() => onCopy(msg.id)} className="text-xs text-zinc-600 hover:text-zinc-400 flex items-center gap-1 transition-colors">
                    <Icons.copy /> 复制
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Tool result */}
        {isTool && tool && (
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0" style={{ backgroundColor: `${tool.color}15`, color: tool.color }}>
              {tool.icon}
            </div>
            <div className="flex-1 min-w-0">
              <div className="px-4 py-3 rounded-2xl rounded-tl-sm border text-sm leading-relaxed bg-zinc-900/80 border-zinc-800 text-zinc-300">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-medium" style={{ color: tool.color }}>工具执行完成</span>
                  <span className="text-xs text-zinc-600">·</span>
                  <span className="text-xs text-zinc-500">{msg.toolName}</span>
                </div>
                {typeof msg.toolResult === "object" ? (
                  <div className="mt-2 text-xs text-zinc-500 font-mono bg-zinc-950 rounded-lg p-3 max-h-48 overflow-y-auto">
                    <pre className="whitespace-pre-wrap">{JSON.stringify(msg.toolResult, null, 2)}</pre>
                  </div>
                ) : (
                  <span className="text-xs text-zinc-400">{String(msg.toolResult)}</span>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ============ Main Chat UI ============
export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [uiAction, setUiAction] = useState<UIAction | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
  }, [messages, uiAction]);

  const sendMessage = useCallback(async (text?: string) => {
    const msgText = text || input.trim();
    if (!msgText || isStreaming) return;

    const userMsg: Message = {
      id: Date.now().toString(),
      role: "user",
      content: msgText,
      timestamp: Date.now(),
    };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setIsStreaming(true);
    if (!text) setUiAction(null);

    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message: msgText, history: [] }),
      });

      const reader = resp.body?.getReader();
      if (!reader) return;

      let buffer = "";
      let currentContent = "";
      const toolResults: Array<{tool_call_id: string; tool_name: string; result: unknown}> = [];

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const text_dec = new TextDecoder().decode(value);
        const lines = (buffer + text_dec).split("\n");

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6);
          if (raw === "[DONE]" || raw === "") continue;

          try {
            const event: StreamEvent = JSON.parse(raw);

            if (event.type === "content" && event.content) {
              currentContent += event.content;
              setMessages(prev => {
                const last = prev[prev.length - 1];
                if (last?.role === "assistant" && !last.toolName) {
                  return [...prev.slice(0, -1), { ...last, content: last.content + event.content! }];
                }
                return [...prev, { id: (Date.now() + 1).toString(), role: "assistant", content: event.content!, timestamp: Date.now() }];
              });
            }

            if (event.type === "tool_result") {
              toolResults.push({ tool_call_id: "", tool_name: event.tool_name || "", result: event.result });
              setMessages(prev => [...prev, {
                id: (Date.now() + toolResults.length).toString(),
                role: "tool",
                content: `工具执行结果`,
                toolName: event.tool_name,
                toolResult: event.result,
                timestamp: Date.now(),
              }]);
            }

            if (event.type === "ui_action" && event.ui_action) {
              setUiAction(event.ui_action);
            }

            if (event.type === "done" && event.session_id) {
              setSessionId(event.session_id);
            }
          } catch { /* skip */ }
        }
        buffer = "";
      }
    } catch (err) {
      setMessages(prev => [...prev, {
        id: (Date.now() + 999).toString(),
        role: "assistant",
        content: `请求失败: ${err instanceof Error ? err.message : "Unknown error"}`,
        timestamp: Date.now(),
      }]);
    } finally {
      setIsStreaming(false);
    }
  }, [input, isStreaming, sessionId]);

  const handleUIAction = (data: Record<string, string>) => {
    setMessages(prev => [...prev, {
      id: Date.now().toString(),
      role: "assistant",
      content: `✅ 已确认映射选择: ${data.selected_id || JSON.stringify(data)}`,
      timestamp: Date.now(),
    }]);
    setUiAction(null);
  };

  return (
    <div className="flex h-screen bg-zinc-950">
      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="flex items-center justify-between px-6 py-4 border-b border-zinc-800/80 bg-zinc-950/80 backdrop-blur-md">
          <div className="flex items-center gap-3">
            <button onClick={() => setSidebarOpen(!sidebarOpen)} className="p-2 rounded-lg hover:bg-zinc-800 transition-colors lg:hidden">
              <Icons.menu />
            </button>
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-600 to-purple-600 flex items-center justify-center">
                <span className="text-sm">🏥</span>
              </div>
              <div>
                <h1 className="text-sm font-bold text-zinc-100">OMOP 数据治理</h1>
                <p className="text-xs text-zinc-500">AI 驱动的医疗数据标准化</p>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {sessionId && (
              <span className="text-xs text-zinc-600 hidden sm:block">Session: {sessionId.slice(0, 8)}</span>
            )}
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-green-500" />
              <span className="text-xs text-zinc-400">在线</span>
            </div>
          </div>
        </header>

        {/* Chat area */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-6">
          {messages.length === 0 ? (
            <EmptyState onSelect={(q) => sendMessage(q)} />
          ) : (
            <div className="max-w-3xl mx-auto space-y-5">
              {messages.map(msg => (
                <div key={msg.id}>
                  <MessageBubble msg={msg} onCopy={(id) => {
                    const m = messages.find(m => m.id === id);
                    if (m) navigator.clipboard.writeText(m.content);
                  }} />
                </div>
              ))}

              {uiAction && (
                <div className="max-w-2xl">
                  {uiAction.type === "PROGRESS_BAR" && (
                    <ProgressBar title={uiAction.title} phase={uiAction.phase as string || "Running"} message={uiAction.message as string || ""} />
                  )}
                  {uiAction.type === "SINGLE_SELECT_CONFIRM" && (
                    <ConfirmDialog title={uiAction.title} term={uiAction.term as string || ""}
                      candidates={(uiAction.candidates || []) as Array<{omop_concept_id: number; concept_name: string; confidence: number}>}
                      message={uiAction.message as string || ""} onConfirm={(id) => handleUIAction({"selected_id": id.toString()})} />
                  )}
                </div>
              )}

              {isStreaming && (
                <TypingIndicator />
              )}
            </div>
          )}
        </div>

        {/* Input */}
        <div className="input-area px-4 py-4">
          <div className="max-w-3xl mx-auto">
            <div className="flex items-center gap-3 bg-zinc-900/80 border border-zinc-800 rounded-2xl px-4 py-2 focus-within:border-indigo-500/50 focus-within:ring-1 focus-within:ring-indigo-500/20 transition-all">
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => e.key === "Enter" && !e.shiftKey && sendMessage()}
                placeholder="输入数据治理指令，如：把 HIS 门诊同步到 OMOP Drug Exposure"
                className="flex-1 bg-transparent text-sm text-zinc-200 placeholder-zinc-600 outline-none"
              />
              <button
                onClick={() => sendMessage()}
                disabled={!input.trim() || isStreaming}
                className="btn-primary w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 disabled:opacity-30 disabled:cursor-not-allowed flex items-center justify-center text-white transition-all flex-shrink-0">
                <Icons.send />
              </button>
            </div>
            <p className="text-xs text-zinc-700 mt-2 text-center">AI 助手基于大模型工作，结果仅供参考</p>
          </div>
        </div>
      </div>
    </div>
  );
}
