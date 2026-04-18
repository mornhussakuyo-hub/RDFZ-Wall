(() => {
    const panel = document.querySelector('[data-ai-summary-panel]');
    if (!panel) {
        return;
    }

    const button = panel.querySelector('[data-ai-summary-button]');
    const badge = panel.querySelector('[data-ai-summary-badge]');
    const status = panel.querySelector('[data-ai-summary-status]');
    const placeholder = panel.querySelector('[data-ai-summary-placeholder]');
    const content = panel.querySelector('[data-ai-summary-content]');
    const meta = panel.querySelector('[data-ai-summary-meta]');
    const ready = panel.dataset.ready === 'true';
    const loggedIn = panel.dataset.loggedIn === 'true';
    const used = panel.dataset.used === 'true';
    const endpoint = panel.dataset.endpoint;
    const defaultLabel = button.textContent.trim();

    const setStatus = (message, state = 'info') => {
        if (!message) {
            status.hidden = true;
            status.textContent = '';
            status.className = 'ai-summary-status';
            return;
        }
        status.hidden = false;
        status.textContent = message;
        status.className = `ai-summary-status is-${state}`;
    };

    const escapeHtml = (value) =>
        value
            .replaceAll('&', '&amp;')
            .replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;')
            .replaceAll('"', '&quot;')
            .replaceAll("'", '&#39;');

    if (!ready) {
        button.disabled = true;
        setStatus('请先在 .env 中配置 AI_SUMMARY_API_KEY 和 AI_SUMMARY_BASE_URL。', 'error');
        return;
    }

    if (!loggedIn) {
        button.disabled = true;
        setStatus('请先登录后再使用 AI 总结功能。', 'error');
        return;
    }

    if (used) {
        button.disabled = true;
        setStatus('你已经使用过本帖 AI 总结了。', 'info');
        return;
    }

    button.addEventListener('click', async () => {
        if (button.disabled) {
            return;
        }

        button.disabled = true;
        button.classList.add('is-loading');
        button.textContent = '生成中...';
        setStatus('AI 努力分析中，这可能会花费一些时间...', 'info');

        try {
            const response = await fetch(endpoint, {
                method: 'POST',
                headers: {
                    'X-Requested-With': 'fetch',
                },
            });
            const data = await response.json();

            if (!response.ok || !data.ok) {
                throw new Error(data.error || data.detail || '生成失败，请稍后重试。');
            }

            placeholder.hidden = true;
            content.hidden = false;
            content.innerHTML = escapeHtml(data.summary).replaceAll('\n', '<br>');
            badge.textContent = '已使用';
            badge.classList.remove('muted');
            badge.classList.add('ok');
            meta.textContent = data.updated_at
                ? `你已使用过本帖 AI 总结 · 最近生成：${data.updated_at}`
                : '你已使用过本帖 AI 总结';
            setStatus(data.generated_now ? 'AI 解释已生成，本帖机会已用完。' : '已读取缓存总结，本帖机会已用完。', 'success');
            button.textContent = '已使用过';
            button.disabled = true;
        } catch (error) {
            setStatus(error.message || '生成失败，请稍后重试。', 'error');
            button.textContent = defaultLabel;
        } finally {
            if (button.textContent !== '已使用过') {
                button.disabled = false;
            }
            button.classList.remove('is-loading');
        }
    });
})();
