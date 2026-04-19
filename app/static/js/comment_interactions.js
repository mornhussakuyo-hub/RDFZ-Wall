document.addEventListener('DOMContentLoaded', () => {
    const panel = document.querySelector('[data-comment-panel]');
    if (!panel) {
        return;
    }

    const rateLimitMessage = panel.dataset.rateLimitMessage || '发送评论太频繁啦！歇一下吧！';
    if (panel.dataset.rateLimited === 'true') {
        requestAnimationFrame(() => {
            window.setTimeout(() => {
                window.alert(rateLimitMessage);
            }, 0);
        });
    }

    const randomItem = (items) => items[Math.floor(Math.random() * items.length)];

    const rootPlaceholders = [
        '下面我简单喵两句',
        '说点什么吧，友善交流哦',
        '来都来了，留下你的看法吧',
        '这一条我有话要说',
        '轻轻放下一句评论',
        '等你一句大实话',
        '评论区的靓仔，请开始你的表演',
        '你的想法，值得被看见',
        '路过不要错过，写点啥呗',
        '键盘给你，随便唠唠',
        '发言前先摸摸头',
        '不说两句再走吗？',
        '让评论区更有趣一点',
        '写一条有灵魂的评论',
        '别潜水，上来喘口气',
        '分享你的小见解',
        '脑洞已打开，请发言',
        '友善吐槽，欢迎你来',
        '每条评论都算数',
        '今日份的思考请投递',
        '留下一朵小浪花吧',
        '你的声音很重要',
        '不抢沙发，只聊真心话',
        '轻轻一点，世界听见你',
        '写点让人会心一笑的话',
        '评论也是一种支持',
        '好评论自带光芒',
        '随手写写，不嫌字数少',
        '这一条我想听你说',
        '水军请绕道，真人请发言',
    ];

    const replyTemplates = [
        (username) => `回复 @${username}： `,
    ];

    const rootTextarea = panel.querySelector('[data-root-comment-textarea]');
    if (rootTextarea) {
        rootTextarea.placeholder = randomItem(rootPlaceholders);
    }

    const replyForms = Array.from(panel.querySelectorAll('[data-reply-form]'));
    const replyTriggers = Array.from(panel.querySelectorAll('[data-reply-trigger]'));

    const closeAllReplyForms = () => {
        replyForms.forEach((form) => {
            form.hidden = true;
            const textarea = form.querySelector('[data-reply-textarea]');
            if (textarea) {
                textarea.value = '';
            }
        });
    };

    replyTriggers.forEach((trigger) => {
        trigger.addEventListener('click', () => {
            const { commentId, commentUsername } = trigger.dataset;
            if (!commentId || !commentUsername) {
                return;
            }

            const targetForm = panel.querySelector(`[data-reply-form][data-comment-id="${commentId}"]`);
            if (!targetForm) {
                return;
            }

            const wasHidden = targetForm.hidden;
            closeAllReplyForms();
            if (!wasHidden) {
                return;
            }

            const hint = targetForm.querySelector('[data-reply-hint]');
            const textarea = targetForm.querySelector('[data-reply-textarea]');
            if (hint) {
                hint.textContent = `回复 @${commentUsername}：`;
            }
            if (textarea) {
                textarea.placeholder = randomItem(replyTemplates)(commentUsername);
            }

            targetForm.hidden = false;
            targetForm.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            if (textarea) {
                textarea.focus({ preventScroll: true });
            }
        });
    });

    replyForms.forEach((form) => {
        const cancelButton = form.querySelector('[data-reply-cancel]');
        if (!cancelButton) {
            return;
        }

        cancelButton.addEventListener('click', () => {
            const textarea = form.querySelector('[data-reply-textarea]');
            if (textarea) {
                textarea.value = '';
            }
            form.hidden = true;
        });
    });
});
