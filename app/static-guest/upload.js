// Small, page-session upload state for public QR problem photos.
// It deliberately has no dependency on the authenticated/offline queue.
(function (root) {
  async function errorDetail(response) {
    const body = await response.json().catch(() => ({}));
    return typeof body.detail === 'string' ? body.detail : 'Не удалось отправить фотографию';
  }

  function isPermanentStatus(status) {
    return [400, 404, 413, 415, 422].includes(status);
  }

  async function upload(photo, { qrToken, requestId, send = fetch }) {
    photo.status = 'uploading';
    photo.error = null;
    photo.retryable = false;
    try {
      const data = new FormData();
      data.append('file', photo.file, photo.name);
      data.append('client_id', photo.id);
      const response = await send(`/api/public/equipment/${qrToken}/requests/${requestId}/attachments`, { method: 'POST', body: data });
      if (!response.ok) {
        photo.status = 'failed';
        photo.error = await errorDetail(response);
        photo.retryable = !isPermanentStatus(response.status);
        return photo;
      }
      photo.status = 'success';
      return photo;
    } catch (_) {
      photo.status = 'failed';
      photo.error = 'Нет связи или сервер временно недоступен';
      photo.retryable = true;
      return photo;
    }
  }

  async function uploadPending(photos, options, onChange = () => {}) {
    for (const photo of photos.filter((item) => item.status === 'pending' || (item.status === 'failed' && item.retryable))) {
      onChange();
      await upload(photo, options);
      onChange();
    }
    return photos;
  }

  root.FixitGuestPhotoUpload = { uploadPending };
})(typeof window === 'undefined' ? globalThis : window);
