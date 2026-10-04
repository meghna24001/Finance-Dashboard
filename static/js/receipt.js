/**
 * FinSight — Receipt Scanner
 * Uploads an image, calls /receipt/scan, pre-fills the transaction form.
 */
(function () {
  document.addEventListener("DOMContentLoaded", function () {
    var zone = document.querySelector(".receipt-zone");
    var fileInputs = document.querySelectorAll("[data-receipt-input]");
    var browseButton = document.querySelector("[data-receipt-browse]");
    var cameraButton = document.querySelector("[data-receipt-camera]");
    var cameraPanel = document.querySelector("[data-receipt-camera-panel]");
    var video = document.querySelector("[data-receipt-video]");
    var canvas = document.querySelector("[data-receipt-canvas]");
    var captureButton = document.querySelector("[data-receipt-capture]");
    var cameraCancelButton = document.querySelector("[data-receipt-camera-cancel]");
    var scanStatus = document.querySelector("[data-scan-status]");
    if (!zone || !fileInputs.length) return;
    var cameraStream = null;

    function showStatus(html) {
      if (scanStatus) scanStatus.innerHTML = html;
    }

    function prefill(data) {
      if (data.amount) {
        var amountField = document.querySelector("[name='amount']");
        if (amountField) amountField.value = data.amount;
      }
      if (data.date) {
        var dateField = document.querySelector("[name='date']");
        if (dateField) dateField.value = data.date;
      }
      if (data.merchant) {
        var descField = document.querySelector("[name='description']");
        if (descField && !descField.value) descField.value = data.merchant;
      }
      showStatus('<span style="color:var(--income)">✓ Receipt scanned — please review and confirm the details.</span>');
    }

    function scanFile(file) {
      if (!file || !file.type.startsWith("image/")) {
        showStatus('<span style="color:var(--danger)">Please select an image file.</span>');
        return;
      }
      showStatus('<span class="receipt-scanning"><span class="spinner"></span> Scanning receipt…</span>');
      var fd = new FormData();
      fd.append("receipt", file);

      // Get CSRF token from meta or hidden field
      var csrf = document.querySelector("[name='csrf_token']");
      if (csrf) fd.append("csrf_token", csrf.value);

      fetch("/receipt/scan", { method: "POST", body: fd, credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.error) {
            showStatus('<span style="color:var(--danger)">Scan incomplete — ' + data.error + '. Please fill in manually.</span>');
          } else {
            prefill(data);
          }
        })
        .catch(function () {
          showStatus('<span style="color:var(--danger)">Scan failed. Please fill in the details manually.</span>');
        });
    }

    function stopCamera() {
      if (cameraStream) {
        cameraStream.getTracks().forEach(function (track) { track.stop(); });
        cameraStream = null;
      }
      if (video) video.srcObject = null;
      if (cameraPanel) cameraPanel.hidden = true;
      if (cameraButton) cameraButton.disabled = false;
    }

    function openCamera() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        var fallbackInput = document.querySelector("[data-receipt-camera-input]");
        showStatus('<span style="color:var(--danger)">Live camera is not supported here. Opening the device camera picker instead.</span>');
        if (fallbackInput) fallbackInput.click();
        return;
      }
      if (!cameraPanel || !video || !cameraButton) return;
      cameraButton.disabled = true;
      showStatus('<span class="receipt-scanning"><span class="spinner"></span> Requesting camera access…</span>');
      navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false })
        .then(function (stream) {
          cameraStream = stream;
          video.srcObject = stream;
          cameraPanel.hidden = false;
          showStatus("Position the receipt inside the frame, then capture it.");
        })
        .catch(function (error) {
          stopCamera();
          var message = error && error.name === "NotAllowedError"
            ? "Camera access is unavailable. Check the camera permission for this app or browser and try again"
            : "The camera could not be opened";
          showStatus('<span style="color:var(--danger)">' + message + '. You can also use Browse files.</span>');
        });
    }

    function capturePhoto() {
      if (!cameraStream || !video || !canvas || !video.videoWidth) {
        showStatus('<span style="color:var(--danger)">The camera is not ready yet. Please try again.</span>');
        return;
      }
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(function (blob) {
        stopCamera();
        if (!blob) {
          showStatus('<span style="color:var(--danger)">Could not capture the photo. Please try again.</span>');
          return;
        }
        scanFile(new File([blob], "receipt-camera.jpg", { type: "image/jpeg" }));
      }, "image/jpeg", 0.9);
    }

    // Click to open file picker
    if (browseButton) {
      browseButton.addEventListener("click", function (event) {
        event.stopPropagation();
        var input = document.querySelector("[data-receipt-browse-input]");
        if (input) input.click();
      });
    }

    if (cameraButton) {
      cameraButton.addEventListener("click", function (event) {
        event.stopPropagation();
        openCamera();
      });
    }
    if (captureButton) captureButton.addEventListener("click", capturePhoto);
    if (cameraCancelButton) cameraCancelButton.addEventListener("click", stopCamera);

    zone.addEventListener("click", function () {
      var input = document.querySelector("[data-receipt-browse-input]");
      if (input) input.click();
    });

    Array.prototype.forEach.call(fileInputs, function (input) {
      input.addEventListener("change", function () {
        if (input.files && input.files[0]) scanFile(input.files[0]);
      });
    });

    // Drag-and-drop
    zone.addEventListener("dragover", function (e) { e.preventDefault(); zone.classList.add("is-dragging"); });
    zone.addEventListener("dragleave", function () { zone.classList.remove("is-dragging"); });
    zone.addEventListener("drop", function (e) {
      e.preventDefault();
      zone.classList.remove("is-dragging");
      var file = e.dataTransfer.files && e.dataTransfer.files[0];
      if (file) scanFile(file);
    });
    window.addEventListener("pagehide", stopCamera);
  });
})();
