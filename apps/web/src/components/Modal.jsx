export default function Modal({ title, onClose, children, wide = false }) {
  return (
    <div className="modal d-block nb-modal" style={{ background: "rgba(0,0,0,.55)" }} onClick={onClose}>
      <div className={`modal-dialog ${wide ? "modal-lg" : ""}`} onClick={(e) => e.stopPropagation()}>
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">{title}</h5>
            <button type="button" className="btn-close" aria-label="Закрыть" onClick={onClose} />
          </div>
          <div className="modal-body">{children}</div>
        </div>
      </div>
    </div>
  );
}
