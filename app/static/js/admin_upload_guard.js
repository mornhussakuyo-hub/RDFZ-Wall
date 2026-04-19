const uploadForm = document.querySelector('[data-upload-form]');

if (uploadForm) {
  const imageInput = uploadForm.querySelector('[data-upload-images]');
  const videoInput = uploadForm.querySelector('[data-upload-videos]');
  const maxUploadFiles = Number(uploadForm.dataset.maxUploadFiles || 0);
  const maxSingleFileMb = Number(uploadForm.dataset.maxSingleFileMb || 0);
  const maxVideoFiles = Number(uploadForm.dataset.maxVideoFiles || 0);
  const maxSingleVideoMb = Number(uploadForm.dataset.maxSingleVideoMb || 0);
  const maxRequestBodyMb = Number(uploadForm.dataset.maxRequestBodyMb || 0);

  const mbToBytes = (value) => value * 1024 * 1024;

  const validateFiles = (files, maxCount, maxSingleMb, label) => {
    if (files.length > maxCount) {
      return `${label}最多只能上传 ${maxCount} 个。`;
    }

    for (const file of files) {
      if (file.size > mbToBytes(maxSingleMb)) {
        return `${label}“${file.name}”超过了 ${maxSingleMb}MB。`;
      }
    }

    return '';
  };

  uploadForm.addEventListener('submit', (event) => {
    const imageFiles = Array.from(imageInput?.files || []);
    const videoFiles = Array.from(videoInput?.files || []);

    const imageError = validateFiles(imageFiles, maxUploadFiles, maxSingleFileMb, '图片');
    if (imageError) {
      event.preventDefault();
      window.alert(imageError);
      return;
    }

    const videoError = validateFiles(videoFiles, maxVideoFiles, maxSingleVideoMb, '视频');
    if (videoError) {
      event.preventDefault();
      window.alert(videoError);
      return;
    }

    const totalBytes = [...imageFiles, ...videoFiles].reduce((sum, file) => sum + file.size, 0);
    if (maxRequestBodyMb > 0 && totalBytes > mbToBytes(maxRequestBodyMb)) {
      event.preventDefault();
      window.alert(`本次上传总大小超过 ${maxRequestBodyMb}MB，容易被服务器拦截，请减少文件数量或压缩后再试。`);
    }
  });
}
