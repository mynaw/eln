import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Editor } from "ketcher-react";
import { StandaloneStructServiceProvider } from "ketcher-standalone";
import "ketcher-react/dist/index.css";

const provider = new StandaloneStructServiceProvider();

// 由 ELN 的本地服务注入；直接双击打开时为空，编辑器仍可用，只是不能回写
const BOOT = window.__ELN_KETCHER__ || {};



function App() {
  const ketcher = useRef(null);
  const loaded = useRef(false);
  const saved = useRef(false);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(BOOT.initial ? "正在载入结构…" : "可以开始画了");

  const onInit = useCallback((k) => {
    ketcher.current = k;
    setReady(true);
  }, []);

  // 直接关窗口时告诉 ELN「这次放弃了」，免得上游一直等
  useEffect(() => {
    const onUnload = () => {
      if (saved.current) return;
      try { navigator.sendBeacon("/api/cancel"); } catch (e) { /* ignore */ }
    };
    window.addEventListener("beforeunload", onUnload);
    return () => window.removeEventListener("beforeunload", onUnload);
  }, []);

  // 编辑器就绪后把 ELN 里的结构塞进去（只做一次）
  useEffect(() => {
    if (!ready || loaded.current) return;
    loaded.current = true;
    const s = BOOT.initial;
    if (!s) return;
    ketcher.current
      .setMolecule(s)
      .then(() => setMsg("已载入 ELN 里的结构"))
      .catch((e) => setMsg("载入失败：" + (e && e.message ? e.message : e)));
  }, [ready]);

  const save = async () => {
    const k = ketcher.current;
    if (!k) return;
    setBusy(true);
    setMsg("正在回写…");
    try {
      const data = {
        smiles: await k.getSmiles().catch(() => ""),
        mol: await k.getMolfile().catch(() => ""),
        // 没有反应箭头时 getRxn 会抛错，属正常情况
        rxn: await k.getRxn().catch(() => ""),
        // CDXML 能保住箭头与文字；部分版本没有这个方法，取不到就算了
        cdxml:
          typeof k.getCDXml === "function"
            ? await k.getCDXml().catch(() => "")
            : "",
      };
      const r = await fetch("/api/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!r.ok) throw new Error("HTTP " + r.status);
      saved.current = true;
      setMsg("已保存，可以关闭这个窗口");
      setTimeout(() => {
        try { window.close(); } catch (e) { /* 浏览器不允许就留着 */ }
      }, 600);
    } catch (e) {
      setMsg("保存失败：" + (e && e.message ? e.message : e));
      setBusy(false);
    }
  };

  const cancel = async () => {
    try { await fetch("/api/cancel", { method: "POST" }); } catch (e) { /* ignore */ }
    try { window.close(); } catch (e) { /* ignore */ }
  };

  return (
    <>
      <div className="bar">
        <b>Ketcher 结构编辑器</b>
        <span className="hint">{msg}</span>
        <span className="sp" />
        <button className="cancel" onClick={cancel}>放弃并关闭</button>
        <button className="ok" onClick={save} disabled={!ready || busy}>
          保存回 ELN
        </button>
      </div>
      <div className="editor">
        <Editor
          staticResourcesUrl={BOOT.staticUrl || "./"}
          structServiceProvider={provider}
          onInit={onInit}
        />
      </div>
    </>
  );
}

createRoot(document.getElementById("root")).render(<App />);
