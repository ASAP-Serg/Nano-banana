export default function Modal({ title, onClose, children, wide = false }) {
  const hasTitle = Boolean(title);
  return (
    <div className="modal d-block nb-modal" style={{ background: "rgba(0,0,0,.55)" }} onClick={onClose}>
      <div className={`modal-dialog ${wide ? "modal-lg" : "modal-dialog-centered"}`} onClick={(e) => e.stopPropagation()}>
        <div className="modal-content nb-modal-card">
          {hasTitle ? (
            <div className="modal-header border-0 pb-0">
              <h5 className="modal-title">{title}</h5>
              <button type="button" className="btn-close" aria-label="Закрыть" onClick={onClose} />
            </div>
          ) : (
            <button type="button" className="nb-modal-x btn-close" aria-label="Закрыть" onClick={onClose} />
          )}
          <div className={`modal-body ${hasTitle ? "" : "pt-4"}`}>{children}</div>
        </div>
      </div>
    </div>
  );
}
