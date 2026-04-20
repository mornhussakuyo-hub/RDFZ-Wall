document.addEventListener('DOMContentLoaded', () => {
    const codeBlocks = document.querySelectorAll('.markdown-content pre');

    const copyText = async (text) => {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
            return;
        }

        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.setAttribute('readonly', '');
        textarea.style.position = 'absolute';
        textarea.style.left = '-9999px';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        textarea.remove();
    };

    codeBlocks.forEach((pre) => {
        const code = pre.querySelector('code');
        if (!code) {
            return;
        }

        pre.classList.add('has-copy-button');

        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'code-copy-button';
        button.textContent = '复制代码';

        let resetTimer = null;
        button.addEventListener('click', async () => {
            try {
                await copyText(code.innerText);
                button.textContent = '已复制';
                button.classList.add('is-success');
            } catch (error) {
                button.textContent = '复制失败';
            }

            if (resetTimer) {
                window.clearTimeout(resetTimer);
            }
            resetTimer = window.setTimeout(() => {
                button.textContent = '复制代码';
                button.classList.remove('is-success');
            }, 1800);
        });

        pre.prepend(button);
    });
});
