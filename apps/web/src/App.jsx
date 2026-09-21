import { useCallback, useEffect, useRef, useState } from "react";
import { api, getToken, setToken } from "./api.js";
import { toast } from "./toast.js";
import Navbar from "./components/Navbar.jsx";
import StatusBar from "./components/StatusBar.jsx";
import GenerateForm from "./components/GenerateForm.jsx";
import Gallery from "./components/Gallery.jsx";
import AdminPanel from "./components/AdminPanel.jsx";
import AuthModals from "./components/AuthModals.jsx";
import KeysModal from "./components/KeysModal.jsx";
import Lightbox from "./components/Lightbox.jsx";
import ParamsModal from "./components/ParamsModal.jsx";

export default function App() {
  const [theme, setTheme] = useState(() => localStorage.getItem("nb_theme") || "dark");
  const [user, setUser] = useState(null);
  const [showLogin, setShowLogin] = useState(false);
  const [showRegister, setShowRegister] = useState(false);
  const [showKeys, setShowKeys] = useState(false);
  const [showAdmin, setShowAdmin] = useState(false);
  const [status, setStatus] = useState(null);
  const [models, setModels] = useState({});
  const [defaultModel, setDefaultModel] = useState("nano-banana-pro");
  const [keys, setKeys] = useState({});
  const [gallery, setGallery] = useState([]);
  const [galleryMeta, setGalleryMeta] = useState(null);
  const [busy, setBusy] = useState(false);
  const [lightbox, setLightbox] = useState(null);
  const [infoItem, setInfoItem] = useState(null);
  const generateRef = useRef(null);

  useEffect(() => {
    document.documentElement.setAttribute("data-bs-theme", theme);
    localStorage.setItem("nb_theme", theme);
  }, [theme]);

  const loadMe = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      return;
    }
    try {
      setUser(await api.me());
    } catch {
      setToken("");
      setUser(null);
    }
  }, []);

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await api.serviceStatus(Boolean(getToken())));
    } catch (err) {
      setStatus({
        state: "unknown",
        message: err.message || "Не удалось получить статус сервисов",
        services: [],
      });
    }
  }, []);

  const loadGallery = useCallback(async () => {
    if (!getToken()) {
      setGallery([]);
      return;
    }
    try {
      const data = await api.list(50, 0);
      setGallery(data.generations || []);
      setGalleryMeta(data.meta || null);
    } catch (err) {
      toast(err.message, "error");
    }
  }, []);

  const loadModels = useCallback(async () => {
    if (!getToken()) return;
    try {
      const data = await api.models();
      setModels(data.models || {});
      setDefaultModel(data.default_model || "nano-banana-pro");
      setKeys(await api.getKeys());
    } catch (err) {
      toast(err.message, "error");
    }
  }, []);

  useEffect(() => {
    loadMe();
    loadStatus();
    const t = setInterval(loadStatus, 30000);
    return () => clearInterval(t);
  }, [loadMe, loadStatus]);

  useEffect(() => {
    if (!user) return;
    loadModels();
    loadGallery();
    const t = setInterval(loadGallery, 4000);
    return () => clearInterval(t);
  }, [user, loadModels, loadGallery]);

  async function onLogin(e) {
    e.preventDefault();
    const form = new FormData(e.target);
    try {
      const tokens = await api.login(form.get("username"), form.get("password"));
      setToken(tokens.access_token);
      setShowLogin(false);
      await loadMe();
      toast("Вход выполнен");
    } catch (err) {
      toast(err.message, "error");
    }
  }

  async function onRegister(e) {
    e.preventDefault();
    const form = new FormData(e.target);
    try {
      const tokens = await api.register(form.get("username"), form.get("email"), form.get("password"));
      setToken(tokens.access_token);
      setShowRegister(false);
      await loadMe();
      toast("Регистрация успешна");
    } catch (err) {
      toast(err.message, "error");
    }
  }

  async function onGenerate(payload) {
    setBusy(true);
    try {
      await api.generate(payload);
      toast("Генерация добавлена в очередь");
      await loadGallery();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function applyFromId(id, opts) {
    try {
      const gen = await api.generation(id);
      generateRef.current?.applyGeneration(gen, opts);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      toast(err.message, "error");
    }
  }

  async function applyAdmin(id) {
    try {
      const gen = await api.adminGeneration(id);
      generateRef.current?.applyGeneration(gen);
      setShowAdmin(false);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      toast(err.message, "error");
    }
  }

  async function retryItem(item) {
    if (!item.fallback_model) {
      toast("Fallback-модель не задана", "error");
      return;
    }
    try {
      const gen = await api.generation(item.id);
      await onGenerate({
        prompt: gen.prompt || "",
        negative_prompt: gen.negative_prompt || null,
        generation_mode: gen.generation_mode || "text-to-image",
        model_name: item.fallback_model,
        resolution: gen.resolution || "1K",
        aspect_ratio: gen.aspect_ratio || "1:1",
        guidance_scale: Number.isFinite(Number(gen.guidance_scale)) ? Number(gen.guidance_scale) : 7.5,
        num_inference_steps: Number.isFinite(Number(gen.num_inference_steps)) ? Number(gen.num_inference_steps) : 50,
        seed: gen.seed ?? null,
        rewrite_prompt: Boolean(gen.rewrite_requested),
        reference_images: Array.isArray(gen.reference_images) ? gen.reference_images : [],
      });
    } catch (err) {
      toast(err.message, "error");
    }
  }

  const lightboxItems = gallery.filter((g) => g.result_url);

  return (
    <>
      <Navbar
        theme={theme}
        onToggleTheme={() => setTheme(theme === "dark" ? "light" : "dark")}
        user={user}
        onLogin={() => setShowLogin(true)}
        onKeys={() => setShowKeys(true)}
        onAdmin={() => setShowAdmin(true)}
        onLogout={() => {
          setToken("");
          setUser(null);
          setGallery([]);
          setShowAdmin(false);
        }}
      />
      <StatusBar status={status} />
      <main className="container-fluid my-4">
        <div className="row g-4 justify-content-center mt-3">
          <div className="col-lg-4">
            <GenerateForm
              ref={generateRef}
              user={user}
              models={models}
              defaultModel={defaultModel}
              busy={busy}
              onGenerate={onGenerate}
              onNeedLogin={() => setShowLogin(true)}
            />
          </div>
          <div className="col-lg-8">
            <Gallery
              user={user}
              gallery={gallery}
              galleryMeta={galleryMeta}
              onRefresh={loadGallery}
              onDelete={async (id) => {
                await api.deleteGeneration(id);
                await loadGallery();
              }}
              onOpen={(idx) => {
                const item = gallery[idx];
                const li = lightboxItems.findIndex((g) => g.id === item.id);
                if (li >= 0) setLightbox(li);
              }}
              onInfo={setInfoItem}
              onReuse={(id) => applyFromId(id)}
              onRetry={retryItem}
            />
          </div>
        </div>
        {showAdmin && user?.is_admin && (
          <AdminPanel onClose={() => setShowAdmin(false)} onInsertToForm={applyAdmin} />
        )}
      </main>
      <AuthModals
        showLogin={showLogin}
        showRegister={showRegister}
        onCloseLogin={() => setShowLogin(false)}
        onCloseRegister={() => setShowRegister(false)}
        onOpenRegister={() => {
          setShowLogin(false);
          setShowRegister(true);
        }}
        onLogin={onLogin}
        onRegister={onRegister}
      />
      {showKeys && <KeysModal keys={keys} onClose={() => setShowKeys(false)} onSaved={setKeys} />}
      {lightbox != null && (
        <Lightbox items={lightboxItems} index={lightbox} onClose={() => setLightbox(null)} onIndex={setLightbox} />
      )}
      {infoItem && <ParamsModal item={infoItem} onClose={() => setInfoItem(null)} />}
      <div id="nb-toast" style={{ display: "none", zIndex: 1080 }} />
    </>
  );
}
