import { useCallback, useEffect, useRef, useState } from "react";
import { api, clearLegacyToken } from "./api.js";
import { isSafeMediaUrl, toast } from "./toast.js";
import Navbar from "./components/Navbar.jsx";
import StatusBar from "./components/StatusBar.jsx";
import GenerateForm from "./components/GenerateForm.jsx";
import Gallery from "./components/Gallery.jsx";
import AdminPanel from "./components/AdminPanel.jsx";
import AuthModals from "./components/AuthModals.jsx";
import AccountModal from "./components/AccountModal.jsx";
import KeysModal from "./components/KeysModal.jsx";
import Lightbox from "./components/Lightbox.jsx";
import ParamsModal from "./components/ParamsModal.jsx";
import TotpSetup from "./components/TotpSetup.jsx";

export default function App() {
  const [theme, setTheme] = useState(() => localStorage.getItem("nb_theme") || "dark");
  const [user, setUser] = useState(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [showLogin, setShowLogin] = useState(false);
  const [showRegister, setShowRegister] = useState(false);
  const [showKeys, setShowKeys] = useState(false);
  const [showAccount, setShowAccount] = useState(false);
  const [showAdmin, setShowAdmin] = useState(false);
  const [showTotp, setShowTotp] = useState(false);
  const [showTotpComplete, setShowTotpComplete] = useState(false);
  const [googleEnabled, setGoogleEnabled] = useState(false);
  const [passwordRegister, setPasswordRegister] = useState(false);
  const [trustedDeviceDays, setTrustedDeviceDays] = useState(30);
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
    clearLegacyToken();
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("data-bs-theme", theme);
    localStorage.setItem("nb_theme", theme);
  }, [theme]);

  useEffect(() => {
    api
      .providers()
      .then((p) => {
        setGoogleEnabled(Boolean(p?.google));
        setPasswordRegister(Boolean(p?.password_register));
        if (p?.trusted_device_days) setTrustedDeviceDays(Number(p.trusted_device_days) || 30);
      })
      .catch(() => {
        setGoogleEnabled(false);
        setPasswordRegister(false);
      });
  }, []);

  const loadMe = useCallback(async () => {
    try {
      setUser(await api.me());
    } catch {
      setUser(null);
    } finally {
      setAuthChecked(true);
    }
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const auth = params.get("auth");
    if (!auth) return;
    const clean = () => {
      const url = new URL(window.location.href);
      url.searchParams.delete("auth");
      url.searchParams.delete("reason");
      window.history.replaceState({}, "", url.pathname + url.search + url.hash);
    };
    if (auth === "ok") {
      clean();
      loadMe().then(() => toast("Вход выполнен"));
    } else if (auth === "totp_required") {
      clean();
      setShowTotpComplete(true);
    } else if (auth === "error") {
      const reason = params.get("reason") || "";
      clean();
      const messages = {
        google_denied: "Вход через Google отменён",
        state: "Ошибка безопасности входа — попробуйте снова",
        token: "Не удалось подтвердить аккаунт Google",
        conflict: "Этот email уже занят",
        disabled: "Аккаунт отключён",
        google_disabled: "Вход через Google не настроен",
      };
      toast(messages[reason] || "Ошибка входа через Google", "error");
    }
  }, [loadMe]);

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await api.serviceStatus(true));
    } catch (err) {
      setStatus({
        state: "unknown",
        message: err.message || "Не удалось получить статус сервисов",
        services: [],
      });
    }
  }, []);

  const loadGallery = useCallback(async () => {
    if (!user) {
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
  }, [user]);

  const loadModels = useCallback(async () => {
    if (!user) return;
    try {
      const data = await api.models();
      setModels(data.models || {});
      setDefaultModel(data.default_model || "nano-banana-pro");
      setKeys(await api.getKeys());
    } catch (err) {
      toast(err.message, "error");
    }
  }, [user]);

  useEffect(() => {
    loadMe();
  }, [loadMe]);

  useEffect(() => {
    if (user?.is_admin && user.totp_enabled === false) {
      setShowTotp(true);
    }
  }, [user]);

  useEffect(() => {
    if (!authChecked) return;
    if (!user) {
      setStatus(null);
      return;
    }
    loadStatus();
    const t = setInterval(loadStatus, 30000);
    return () => clearInterval(t);
  }, [authChecked, user, loadStatus]);

  useEffect(() => {
    if (!user) return;
    loadModels();
    loadGallery();
    const t = setInterval(loadGallery, 4000);
    return () => clearInterval(t);
  }, [user, loadModels, loadGallery]);

  async function onLogin(form, rememberDevice) {
    try {
      await api.login(form.get("username"), form.get("password"), form.get("totp"), rememberDevice);
      clearLegacyToken();
      setShowLogin(false);
      await loadMe();
      toast("Вход выполнен");
    } catch (err) {
      toast(err.message, "error");
    }
  }

  async function onTotpComplete(code, rememberDevice) {
    try {
      await api.totpComplete(code, rememberDevice);
      clearLegacyToken();
      setShowTotpComplete(false);
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
      await api.register(form.get("username"), form.get("email"), form.get("password"));
      clearLegacyToken();
      setShowRegister(false);
      await loadMe();
      toast("Регистрация успешна");
    } catch (err) {
      toast(err.message, "error");
    }
  }

  async function onLogout() {
    try {
      await api.logout();
    } catch {
      /* ignore */
    }
    clearLegacyToken();
    setUser(null);
    setGallery([]);
    setShowAdmin(false);
    setShowTotp(false);
    setNeedTotp(false);
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
      const hint = opts?.hint;
      generateRef.current?.applyGeneration(
        {
          ...gen,
          mosaic: gen?.mosaic || hint?.mosaic || gen?.generation_mode === "mosaic" || hint?.generation_mode === "mosaic",
          mosaic_kind: gen?.mosaic_kind || hint?.mosaic_kind,
          generation_mode:
            gen?.generation_mode === "mosaic" || hint?.generation_mode === "mosaic" || hint?.mosaic
              ? "mosaic"
              : gen?.generation_mode,
        },
        opts
      );
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      toast(err.message, "error");
    }
  }

  async function applyAdmin(id) {
    try {
      const gen = await api.adminGeneration(id);
      const mosaic = gen.generation_mode === "mosaic" || gen.mosaic || gen.mosaic_kind;
      const refs = [];
      if (!mosaic && gen.result_url) refs.push(gen.result_url);
      for (const url of gen.reference_images || []) {
        if (url && !refs.includes(url) && refs.length < 4) refs.push(url);
      }
      generateRef.current?.applyGeneration({
        ...gen,
        reference_images: mosaic ? gen.reference_images || [] : refs.length ? refs : gen.reference_images,
        generation_mode: mosaic ? "mosaic" : refs.length ? "image-to-image" : gen.generation_mode,
      });
      document.getElementById("generate-form")?.scrollIntoView({ behavior: "smooth", block: "start" });
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

  const lightboxItems = gallery.filter((g) => isSafeMediaUrl(g.result_url));

  return (
    <>
      <Navbar
        theme={theme}
        onToggleTheme={() => setTheme(theme === "dark" ? "light" : "dark")}
        user={user}
        onLogin={() => setShowLogin(true)}
        onKeys={() => setShowKeys(true)}
        onAccount={() => setShowAccount(true)}
        onAdmin={() => {
          if (user?.is_admin && !user.totp_enabled) setShowTotp(true);
          else setShowAdmin(true);
        }}
        onTotp={() => setShowTotp(true)}
        onLogout={onLogout}
      />
      <StatusBar status={status} />
      <main className="container-fluid my-4">
        <div className="nb-workspace">
          <div className="nb-workspace-form">
            <GenerateForm
              ref={generateRef}
              user={user}
              models={models}
              defaultModel={defaultModel}
              keys={keys}
              busy={busy}
              onGenerate={onGenerate}
              onNeedLogin={() => setShowLogin(true)}
              onNeedKeys={() => setShowKeys(true)}
            />
          </div>
          <div className="nb-workspace-gallery">
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
              onReuse={(item) => applyFromId(item.id, { hint: item })}
              onRetry={retryItem}
            />
          </div>
        </div>
        {showAdmin && user?.is_admin && user?.totp_enabled && (
          <AdminPanel onClose={() => setShowAdmin(false)} onInsertToForm={applyAdmin} />
        )}
      </main>
      <AuthModals
        showLogin={showLogin}
        showRegister={showRegister}
        showTotpComplete={showTotpComplete}
        onCloseLogin={() => setShowLogin(false)}
        onCloseRegister={() => setShowRegister(false)}
        onCloseTotpComplete={() => setShowTotpComplete(false)}
        onOpenRegister={() => {
          setShowLogin(false);
          setShowRegister(true);
        }}
        onOpenLogin={() => {
          setShowRegister(false);
          setShowLogin(true);
        }}
        onLogin={onLogin}
        onRegister={onRegister}
        onTotpComplete={onTotpComplete}
        googleEnabled={googleEnabled}
        passwordRegister={passwordRegister}
        trustedDeviceDays={trustedDeviceDays}
      />
      {showTotp && user?.is_admin && !user.totp_enabled && (
        <TotpSetup
          onClose={() => setShowTotp(false)}
          onEnabled={async () => {
            setShowTotp(false);
            await loadMe();
          }}
        />
      )}
      {showAccount && user && (
        <AccountModal
          user={user}
          onClose={() => setShowAccount(false)}
          onUsernameChanged={(next) => setUser(next)}
        />
      )}
      {showKeys && (
        <KeysModal
          keys={keys}
          onClose={() => setShowKeys(false)}
          onSaved={(next) => {
            setKeys(next);
            loadModels();
          }}
        />
      )}
      {lightbox != null && (
        <Lightbox items={lightboxItems} index={lightbox} onClose={() => setLightbox(null)} onIndex={setLightbox} />
      )}
      {infoItem && <ParamsModal item={infoItem} onClose={() => setInfoItem(null)} />}
      <div id="nb-toast" style={{ display: "none", zIndex: 1080 }} />
    </>
  );
}
