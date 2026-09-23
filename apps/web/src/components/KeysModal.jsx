import { api } from "../api.js";
import { toast } from "../toast.js";
import Modal from "./Modal.jsx";

export default function KeysModal({ keys, onClose, onSaved }) {
  async function onSaveKeys(e) {
    e.preventDefault();
    const form = new FormData(e.target);
    try {
      const banana = (form.get("banana") || "").trim();
      const replicate = (form.get("replicate") || "").trim();
      const openrouter = (form.get("openrouter") || "").trim();
      if (banana) await api.setKey(banana, "bananalab");
      if (replicate) await api.setKey(replicate, "replicate");
      if (openrouter) await api.setKey(openrouter, "openrouter");
      onSaved(await api.getKeys());
      toast("Ключи сохранены");
    } catch (err) {
      toast(err.message, "error");
    }
  }

  return (
    <Modal title="API ключи" onClose={onClose}>
      <p className="small">
        Ключи хранятся на сервере в зашифрованном виде. Moonez — <code>bh_</code>, Replicate — <code>r8_</code>, OpenRouter —{" "}
        <code>sk-or</code>.
      </p>
      <p className="small">
        Кабинет Moonez:{" "}
        <a href="https://moonez.ai" target="_blank" rel="noreferrer">
          moonez.ai
        </a>
        {" · "}
        ключи и <strong>IP Whitelist</strong> в панели. Без IP сервера Moonez отвечает 403.{" "}
        <a href="https://docs.moonez.ai/authentication" target="_blank" rel="noreferrer">
          Документация
        </a>
      </p>
      <p className="small text-muted">
        Сейчас: Moonez {keys.has_bananalab_key ? "есть" : "нет"}, Replicate {keys.has_replicate_key ? "есть" : "нет"}, OpenRouter{" "}
        {keys.has_openrouter_key ? "есть" : "нет"}
      </p>
      <form onSubmit={onSaveKeys}>
        <label className="form-label">Moonez</label>
        <input className="form-control mb-2" name="banana" placeholder="bh_..." autoComplete="off" />
        <label className="form-label">Replicate</label>
        <input className="form-control mb-2" name="replicate" placeholder="r8_..." autoComplete="off" />
        <label className="form-label">OpenRouter</label>
        <input className="form-control mb-3" name="openrouter" placeholder="sk-or-..." autoComplete="off" />
        <div className="d-flex gap-2">
          <button className="btn btn-warning flex-fill">Сохранить</button>
          <button
            type="button"
            className="btn btn-outline-danger"
            onClick={async () => {
              await api.deleteKeys();
              onSaved(await api.getKeys());
              toast("Ключи удалены");
            }}
          >
            Удалить
          </button>
        </div>
      </form>
    </Modal>
  );
}
