// Roommate Split - Product-Grade Client Logic

document.addEventListener("DOMContentLoaded", () => {
  // --------------------------------------------------------------------------
  // 1. Dark Mode Toggle
  // --------------------------------------------------------------------------
  const themeToggleBtns = document.querySelectorAll(".theme-toggle-btn");
  const getTheme = () => document.documentElement.getAttribute("data-theme") || "light";

  const setTheme = (theme) => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
    updateThemeIcons(theme);
  };

  const updateThemeIcons = (theme) => {
    themeToggleBtns.forEach((btn) => {
      const sunIcon = btn.querySelector(".sun-icon");
      const moonIcon = btn.querySelector(".moon-icon");
      if (sunIcon && moonIcon) {
        if (theme === "dark") {
          sunIcon.style.display = "block";
          moonIcon.style.display = "none";
        } else {
          sunIcon.style.display = "none";
          moonIcon.style.display = "block";
        }
      }
    });
  };

  updateThemeIcons(getTheme());

  themeToggleBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const nextTheme = getTheme() === "dark" ? "light" : "dark";
      setTheme(nextTheme);
    });
  });

  // --------------------------------------------------------------------------
  // 2. French Currency Formatter Helper
  // --------------------------------------------------------------------------
  const formatMadFrench = (centimes) => {
    const sign = centimes < 0 ? "-" : "";
    const abs = Math.abs(centimes);
    const mad = Math.floor(abs / 100);
    const c = String(abs % 100).padStart(2, "0");
    const madStr = mad.toLocaleString("fr-FR").replace(/\u202f/g, " ");
    return `${sign}${madStr},${c} MAD`;
  };

  // --------------------------------------------------------------------------
  // 3. Animated Count-Up for Hero Balance
  // --------------------------------------------------------------------------
  const countUpElements = document.querySelectorAll("[data-count-target]");
  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  countUpElements.forEach((el) => {
    const target = parseInt(el.getAttribute("data-count-target"), 10);
    if (isNaN(target)) return;

    if (prefersReducedMotion) {
      el.textContent = formatMadFrench(target);
      return;
    }

    const duration = 750; // ms
    const startTime = performance.now();

    const updateCount = (currentTime) => {
      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);
      // Ease out cubic
      const ease = 1 - Math.pow(1 - progress, 3);
      const currentCentimes = Math.round(target * ease);
      el.textContent = formatMadFrench(currentCentimes);

      if (progress < 1) {
        requestAnimationFrame(updateCount);
      } else {
        el.textContent = formatMadFrench(target);
      }
    };

    requestAnimationFrame(updateCount);
  });

  // --------------------------------------------------------------------------
  // 4. Toast Notifications
  // --------------------------------------------------------------------------
  const toasts = document.querySelectorAll(".toast");
  toasts.forEach((toast) => {
    // Auto dismiss after 4.5 seconds
    const timer = setTimeout(() => {
      dismissToast(toast);
    }, 4500);

    const closeBtn = toast.querySelector(".toast-close");
    if (closeBtn) {
      closeBtn.addEventListener("click", () => {
        clearTimeout(timer);
        dismissToast(toast);
      });
    }
  });

  function dismissToast(toast) {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(-10px) scale(0.95)";
    toast.style.transition = "all 0.25s ease";
    setTimeout(() => toast.remove(), 250);
  }

  // --------------------------------------------------------------------------
  // 5. Open on Phone Modal
  // --------------------------------------------------------------------------
  const openPhoneBtn = document.getElementById("openPhoneBtn");
  const phoneModal = document.getElementById("phoneModal");
  const copyPhoneUrlBtn = document.getElementById("copyPhoneUrlBtn");
  const phoneUrlText = document.getElementById("phoneUrlText");

  if (openPhoneBtn && phoneModal) {
    openPhoneBtn.addEventListener("click", () => {
      phoneModal.classList.add("active");
    });

    if (copyPhoneUrlBtn && phoneUrlText) {
      copyPhoneUrlBtn.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(phoneUrlText.textContent.trim());
          const originalText = copyPhoneUrlBtn.textContent;
          copyPhoneUrlBtn.textContent = "Copied!";
          setTimeout(() => {
            copyPhoneUrlBtn.textContent = originalText;
          }, 2000);
        } catch (err) {
          // Fallback
        }
      });
    }
  }

  // --------------------------------------------------------------------------
  // 6. Mark as Settled Confirmation Modal
  // --------------------------------------------------------------------------
  const settleUpBtn = document.getElementById("settleUpBtn");
  const settleModal = document.getElementById("settleModal");
  const confirmSettleBtn = document.getElementById("confirmSettleBtn");
  const settleForm = document.getElementById("settleForm");

  if (settleUpBtn && settleModal) {
    settleUpBtn.addEventListener("click", (e) => {
      e.preventDefault();
      settleModal.classList.add("active");
    });

    if (confirmSettleBtn && settleForm) {
      confirmSettleBtn.addEventListener("click", () => {
        settleForm.submit();
      });
    }
  }

  // --------------------------------------------------------------------------
  // 7. Modals Global Close
  // --------------------------------------------------------------------------
  const allModals = document.querySelectorAll(".modal-backdrop");
  allModals.forEach((modal) => {
    modal.addEventListener("click", (e) => {
      if (e.target === modal || e.target.closest(".close-modal")) {
        modal.classList.remove("active");
      }
    });
  });

  // Close modals on Escape key
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      allModals.forEach((modal) => modal.classList.remove("active"));
    }
  });

  // --------------------------------------------------------------------------
  // 7b. Universal Custom Confirmation Modal Window
  // --------------------------------------------------------------------------
  const confirmModal = document.getElementById("confirmModal");
  const confirmModalTitle = document.getElementById("confirmModalTitle");
  const confirmModalMessage = document.getElementById("confirmModalMessage");
  const confirmModalItemBox = document.getElementById("confirmModalItemBox");
  const confirmModalItemLabel = document.getElementById("confirmModalItemLabel");
  const confirmModalItemAmount = document.getElementById("confirmModalItemAmount");
  const confirmModalProceedBtn = document.getElementById("confirmModalProceedBtn");
  const confirmModalCancelBtn = document.getElementById("confirmModalCancelBtn");
  let pendingConfirmCallback = null;

  window.openConfirmModal = function({
    title = "Confirm Action",
    message = "Are you sure you want to proceed?",
    itemLabel = "",
    itemAmount = "",
    confirmText = "Delete",
    confirmClass = "btn-danger",
    onConfirm = null,
  }) {
    if (!confirmModal) {
      if (typeof onConfirm === "function") onConfirm();
      return;
    }
    if (confirmModalTitle) confirmModalTitle.textContent = title;
    if (confirmModalMessage) confirmModalMessage.textContent = message;
    
    if (confirmModalItemBox) {
      if (itemLabel) {
        if (confirmModalItemLabel) confirmModalItemLabel.textContent = itemLabel;
        if (confirmModalItemAmount) {
          if (itemAmount) {
            confirmModalItemAmount.textContent = itemAmount;
            confirmModalItemAmount.style.display = "inline-block";
          } else {
            confirmModalItemAmount.style.display = "none";
          }
        }
        confirmModalItemBox.style.display = "block";
      } else {
        confirmModalItemBox.style.display = "none";
      }
    }

    if (confirmModalProceedBtn) {
      confirmModalProceedBtn.textContent = confirmText;
      confirmModalProceedBtn.className = "btn " + confirmClass;
    }
    pendingConfirmCallback = onConfirm;
    confirmModal.classList.add("active");
    if (confirmModalCancelBtn) {
      setTimeout(() => confirmModalCancelBtn.focus(), 50);
    }
  };

  if (confirmModalProceedBtn) {
    confirmModalProceedBtn.addEventListener("click", () => {
      confirmModal.classList.remove("active");
      if (typeof pendingConfirmCallback === "function") {
        const cb = pendingConfirmCallback;
        pendingConfirmCallback = null;
        cb();
      }
    });
  }

  // Helper to extract confirm parameters and show dialog
  function handleFormConfirm(form) {
    const confirmMsg = form.getAttribute("data-confirm");
    if (confirmMsg && !form.dataset.confirmed) {
      const title = form.getAttribute("data-confirm-title") || "Confirm Action";
      const itemLabel = form.getAttribute("data-confirm-item") || "";
      const itemAmount = form.getAttribute("data-confirm-amount") || "";
      const confirmText = form.getAttribute("data-confirm-btn") || "Delete";
      const confirmClass = form.getAttribute("data-confirm-class") || "btn-danger";

      window.openConfirmModal({
        title,
        message: confirmMsg,
        itemLabel,
        itemAmount,
        confirmText,
        confirmClass,
        onConfirm: () => {
          form.dataset.confirmed = "true";
          form.submit();
        },
      });
      return true;
    }
    return false;
  }

  // Intercept any form with data-confirm attribute
  document.addEventListener("submit", (e) => {
    const form = e.target;
    if (!form || !form.getAttribute) return;
    if (handleFormConfirm(form)) {
      e.preventDefault();
    }
  });

  // Proactively clean any legacy inline onsubmit with confirm
  document.querySelectorAll("form").forEach((form) => {
    const os = form.getAttribute("onsubmit");
    if (os && os.includes("confirm")) {
      form.removeAttribute("onsubmit");
    }
  });

  // Capture-phase click listener to guarantee popup opens BEFORE any native events
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("button[type='submit'], input[type='submit'], button:not([type])");
    if (!btn) return;
    const form = btn.closest("form");
    if (!form) return;
    if (form.getAttribute("data-confirm") && !form.dataset.confirmed) {
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      handleFormConfirm(form);
    }
  }, true);

  // --------------------------------------------------------------------------
  // 8. Expense Form: Participant Selection & Payer Sync
  // --------------------------------------------------------------------------
  const participantCards = document.querySelectorAll(".participant-select-card");
  participantCards.forEach((card) => {
    const cb = card.querySelector('input[type="checkbox"]');
    if (!cb) return;

    const syncCard = () => {
      if (cb.checked) {
        card.classList.add("selected");
      } else {
        card.classList.remove("selected");
      }
    };

    syncCard();
    cb.addEventListener("change", syncCard);

    card.addEventListener("click", (e) => {
      if (e.target !== cb) {
        cb.checked = !cb.checked;
        cb.dispatchEvent(new Event("change"));
      }
    });
  });

  const selectAllBtn = document.getElementById("selectAllParticipants");
  const deselectAllBtn = document.getElementById("deselectAllParticipants");
  const participantCheckboxes = document.querySelectorAll('input[name="participants"]');

  if (selectAllBtn && participantCheckboxes.length > 0) {
    selectAllBtn.addEventListener("click", () => {
      participantCheckboxes.forEach((cb) => {
        cb.checked = true;
        cb.dispatchEvent(new Event("change"));
      });
    });
  }

  if (deselectAllBtn && participantCheckboxes.length > 0) {
    deselectAllBtn.addEventListener("click", () => {
      participantCheckboxes.forEach((cb) => {
        cb.checked = false;
        cb.dispatchEvent(new Event("change"));
      });
    });
  }

  const payerSelect = document.getElementById("paid_by_id");
  if (payerSelect) {
    const syncPayerState = () => {
      const selectedPayerId = payerSelect.value;
      document.querySelectorAll(".payer-badge").forEach((b) => (b.style.display = "none"));
      if (selectedPayerId) {
        const payerCheckbox = document.getElementById(`cb-participant-${selectedPayerId}`);
        const payerBadge = document.getElementById(`badge-payer-${selectedPayerId}`);
        if (payerCheckbox) {
          payerCheckbox.checked = true;
          payerCheckbox.dispatchEvent(new Event("change"));
        }
        if (payerBadge) {
          payerBadge.style.display = "inline-flex";
        }
      }
    };
    payerSelect.addEventListener("change", syncPayerState);
    syncPayerState();
  }

  // --------------------------------------------------------------------------
  // 9. Rename Roommate Modal
  // --------------------------------------------------------------------------
  const renameButtons = document.querySelectorAll(".open-rename-modal");
  const renameModal = document.getElementById("renameModal");
  const renameForm = document.getElementById("renameForm");
  const renameInput = document.getElementById("renameRoommateName");

  if (renameButtons.length > 0 && renameModal) {
    renameButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-id");
        const currentName = btn.getAttribute("data-name");
        renameForm.action = `/roommates/${id}/rename`;
        renameInput.value = currentName;
        renameModal.classList.add("active");
        renameInput.focus();
      });
    });
  }

  // --------------------------------------------------------------------------
  // 9b. Profile Picture (Avatar) Modal
  // --------------------------------------------------------------------------
  const avatarModal = document.getElementById("avatarModal");
  const openAvatarBtns = document.querySelectorAll(".open-avatar-modal");
  const avatarUploadForm = document.getElementById("avatarUploadForm");
  const avatarRemoveForm = document.getElementById("avatarRemoveForm");
  const avatarFileInput = document.getElementById("avatarFileInput");
  const avatarModalTitle = document.getElementById("avatarModalTitle");
  const avatarModalSubtitle = document.getElementById("avatarModalSubtitle");
  const avatarModalPreview = document.getElementById("avatarModalPreview");
  const avatarRemoveBtn = document.getElementById("avatarRemoveBtn");

  if (avatarModal && openAvatarBtns.length > 0) {
    openAvatarBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-id");
        const name = btn.getAttribute("data-name");
        const initials = btn.getAttribute("data-initials") || "??";
        const gradient = btn.getAttribute("data-gradient") || "var(--primary)";
        const avatarUrl = btn.getAttribute("data-avatar") || "";

        if (avatarUploadForm) avatarUploadForm.action = `/roommates/${id}/avatar`;
        if (avatarRemoveForm) avatarRemoveForm.action = `/roommates/${id}/avatar/remove`;
        if (avatarModalTitle) avatarModalTitle.textContent = `Profile Picture · ${name}`;
        if (avatarModalSubtitle) avatarModalSubtitle.textContent = `Upload or change picture for ${name}`;

        if (avatarFileInput) avatarFileInput.value = "";

        updateAvatarPreview(avatarUrl, initials, gradient, name);

        if (avatarRemoveBtn) {
          avatarRemoveBtn.style.display = avatarUrl ? "inline-flex" : "none";
        }

        avatarModal.classList.add("active");
      });
    });

    function updateAvatarPreview(url, initials, gradient, altName) {
      if (!avatarModalPreview) return;
      if (url) {
        avatarModalPreview.style.background = "transparent";
        avatarModalPreview.innerHTML = `<img src="${url}" alt="${altName || ''}" style="width:100%;height:100%;object-fit:cover;border-radius:var(--radius-full);">`;
      } else {
        avatarModalPreview.style.background = gradient || "var(--primary)";
        avatarModalPreview.innerHTML = `<span>${initials || '??'}</span>`;
      }
    }

    if (avatarFileInput) {
      avatarFileInput.addEventListener("change", (e) => {
        const file = e.target.files && e.target.files[0];
        if (file) {
          const reader = new FileReader();
          reader.onload = (event) => {
            updateAvatarPreview(event.target.result, "", "", "Preview");
          };
          reader.readAsDataURL(file);
        }
      });
    }

    if (avatarRemoveBtn && avatarRemoveForm) {
      avatarRemoveBtn.addEventListener("click", () => {
        if (confirm("Remove profile picture and revert to initials badge?")) {
          avatarRemoveForm.submit();
        }
      });
    }
  }

  // --------------------------------------------------------------------------
  // 10. Record Payment Modal (Settlement Transfers & Generic)
  // --------------------------------------------------------------------------
  const paymentModal = document.getElementById("paymentModal");
  const openPaymentBtns = document.querySelectorAll(".open-payment-modal");
  const closePaymentBtns = document.querySelectorAll(".close-payment-modal");

  const payModalFromId = document.getElementById("payModalFromId");
  const payModalToId = document.getElementById("payModalToId");
  const payModalFromName = document.getElementById("payModalFromName");
  const payModalToName = document.getElementById("payModalToName");
  const payModalFromAvatar = document.getElementById("payModalFromAvatar");
  const payModalToAvatar = document.getElementById("payModalToAvatar");
  const payAmountInput = document.getElementById("payAmountInput");
  const payFullBtn = document.getElementById("payFullBtn");

  if (paymentModal && openPaymentBtns.length > 0) {
    let fullAmountValue = "";

    openPaymentBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        const fromId = btn.getAttribute("data-from-id");
        const fromName = btn.getAttribute("data-from-name");
        const fromInitials = btn.getAttribute("data-from-initials");
        const fromGradient = btn.getAttribute("data-from-gradient");
        const fromAvatar = btn.getAttribute("data-from-avatar");

        const toId = btn.getAttribute("data-to-id");
        const toName = btn.getAttribute("data-to-name");
        const toInitials = btn.getAttribute("data-to-initials");
        const toGradient = btn.getAttribute("data-to-gradient");
        const toAvatar = btn.getAttribute("data-to-avatar");

        const amountCentimes = parseInt(btn.getAttribute("data-amount"), 10);
        fullAmountValue = (amountCentimes / 100).toFixed(2).replace(".", ",");

        if (payModalFromId) payModalFromId.value = fromId;
        if (payModalToId) payModalToId.value = toId;
        if (payModalFromName) payModalFromName.textContent = fromName;
        if (payModalToName) payModalToName.textContent = toName;

        if (payModalFromAvatar) {
          if (fromAvatar) {
            payModalFromAvatar.style.background = "transparent";
            payModalFromAvatar.innerHTML = `<img src="${fromAvatar}" alt="${fromName}" style="width:100%;height:100%;object-fit:cover;border-radius:var(--radius-full);">`;
          } else {
            payModalFromAvatar.textContent = fromInitials;
            payModalFromAvatar.style.background = fromGradient;
          }
        }
        if (payModalToAvatar) {
          if (toAvatar) {
            payModalToAvatar.style.background = "transparent";
            payModalToAvatar.innerHTML = `<img src="${toAvatar}" alt="${toName}" style="width:100%;height:100%;object-fit:cover;border-radius:var(--radius-full);">`;
          } else {
            payModalToAvatar.textContent = toInitials;
            payModalToAvatar.style.background = toGradient;
          }
        }

        if (payAmountInput) {
          payAmountInput.value = fullAmountValue;
        }

        if (payFullBtn) {
          payFullBtn.textContent = `Pay in full (${fullAmountValue} MAD)`;
        }

        paymentModal.classList.add("active");
        if (payAmountInput) {
          payAmountInput.focus();
          payAmountInput.select();
        }
      });
    });

    if (payFullBtn && payAmountInput) {
      payFullBtn.addEventListener("click", () => {
        payAmountInput.value = fullAmountValue;
        payAmountInput.focus();
      });
    }

    closePaymentBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        paymentModal.classList.remove("active");
      });
    });
  }
});
