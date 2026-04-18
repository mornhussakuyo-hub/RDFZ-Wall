(() => {
    const forms = Array.from(document.querySelectorAll('[data-admin-ai-form]'));
    const status = document.querySelector('[data-admin-ai-status]');
    if (!forms.length || !status) {
        return;
    }

    const setStatus = (message, level = 'success') => {
        status.hidden = !message;
        status.textContent = message || '';
        status.className = `alert ${level}`;
    };

    forms.forEach((form) => {
        const row = form.closest('tr');
        const actionWrap = form.closest('[data-admin-post-row]');
        const button = form.querySelector('[data-admin-ai-button]');
        const badge = row?.querySelector('[data-ai-summary-badge]');
        const time = row?.querySelector('[data-ai-summary-time]');
        const defaultText = button?.textContent?.trim() || '重生成AI';
        const originalBadgeText = badge?.textContent?.trim() || '未生成';
        const originalBadgeClass = badge?.className || 'badge muted';
        const originalTimeText = time?.textContent?.trim() || '尚未生成';

        if (actionWrap?.dataset.generating === 'true' && button) {
            button.disabled = true;
            button.textContent = '生成中...';
        }

        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            if (!button) {
                return;
            }

            button.disabled = true;
            button.textContent = '生成中...';
            if (actionWrap) {
                actionWrap.dataset.generating = 'true';
            }
            if (badge) {
                badge.textContent = '生成中';
                badge.classList.remove('muted', 'ok');
            }
            if (time) {
                time.textContent = '正在请求大模型...';
            }
            setStatus('');

            try {
                const response = await fetch(form.action, {
                    method: 'POST',
                    headers: {
                        'X-Requested-With': 'fetch',
                    },
                });
                const data = await response.json();
                if (!response.ok || !data.ok) {
                    throw new Error(data.error || 'AI 总结生成失败，请稍后重试。');
                }

                if (badge) {
                    badge.textContent = '已生成';
                    badge.classList.remove('muted');
                    badge.classList.add('ok');
                }
                if (time) {
                    time.textContent = `更新于 ${data.updated_at}`;
                }
                if (actionWrap) {
                    actionWrap.dataset.generating = 'false';
                }
                setStatus(data.message || 'AI 总结已重新生成。', 'success');
            } catch (error) {
                if (actionWrap) {
                    actionWrap.dataset.generating = 'false';
                }
                if (badge) {
                    badge.textContent = originalBadgeText;
                    badge.className = originalBadgeClass;
                }
                if (time) {
                    time.textContent = originalTimeText;
                }
                setStatus(error.message || 'AI 总结生成失败，请稍后重试。', 'error');
            } finally {
                if (actionWrap?.dataset.generating !== 'true') {
                    button.disabled = false;
                    button.textContent = defaultText;
                }
            }
        });
    });
})();
