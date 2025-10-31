(() => {
    const addLoginExplanation = () => {
        const loginHeaders = Array.from(document.querySelectorAll('div'));
        const loginHeader = loginHeaders.find(el => 
            el.textContent.trim() === '로그인' && 
            el.classList.contains('text-4xl') && 
            el.classList.contains('font-bold')
        );

        if (loginHeader) {
            if (document.getElementById('gemini-login-explanation')) {
                return;
            }
            const explanation = document.createElement('p');
            explanation.id = 'gemini-login-explanation';
            explanation.textContent = '이미지 생성 자동화는 크롤러 봇(Crawler Bot)이 웹사이트에서 직접 사용자를 대신해서 이미지를 생성하는 방식으로 작동합니다. \n 이를 위해, 최초 1회 수동 로그인이 필요하며, 이는 내부적으로만 이용될 뿐, 절대 외부로 유출하지 않습니다. \n 로그인 완료 후 이 브라우저를 닫으면 설정이 완료됩니다. \n 구글을 비롯한 소셜 로그인은 서드파티 기능으로, 크롤러를 감지하고 차단할수 있어, 이메일 로그인 방식을 이용해주시기 바랍니다.';
            explanation.style.fontSize = '13px';
            explanation.style.color = '#9e9e9e';
            explanation.style.textAlign = 'center';
            explanation.style.marginTop = '4px';
            explanation.style.fontWeight = 'normal';
            loginHeader.parentNode.insertBefore(explanation, loginHeader.nextSibling);
        }
    };

    const disableSocialLogins = () => {
        const socialKeys = ["google", "discord", "twitter", "x"];
        const buttons = Array.from(document.querySelectorAll('form button[type="button"], form button, button'));
        let changed = false;
        buttons.forEach(btn => {
            try {
                let text = (btn.innerText || btn.textContent || "").trim();
                if (!text) return;
                const compressed = text.replace(/\s+/g, '').toLowerCase();
                if (compressed.includes('이메일')) return;
                if (compressed.includes('로그인') && socialKeys.some(k => compressed.includes(k))) {
                    if (btn.disabled) return;
                    btn.disabled = true;
                    btn.style.pointerEvents = 'none';
                    btn.style.opacity = '0.5';
                    btn.style.cursor = 'not-allowed';
                    const labelSpan = btn.querySelector('span.normal-case, span');
                    if (labelSpan && labelSpan.textContent) {
                        labelSpan.textContent = labelSpan.textContent.replace(/(google|discord|twitter|x).*$/i, match => {
                            const platform = match.replace(/로그인|사용/ig, '').trim();
                            return (platform || match) + ' 로그인은 지원되지 않습니다.';
                        });
                    } else {
                        btn.textContent = (btn.textContent || '').replace(/로그인.*/i, '') + ' 로그인은 지원되지 않습니다.';
                    }
                    const badge = btn.querySelector('[class*="recommended"], [class*="bg-recommended-badge"], div.h-6, div[class*="recommended-badge"]');
                    if (badge) badge.remove();
                    changed = true;
                }
            } catch {} 
        });
        if (changed) {
            console.log("[PixAI Stealth] 소셜 로그인 버튼 비활성화됨");
        }
    };

    const runStealthSetup = () => {
        disableSocialLogins();
        addLoginExplanation();
    };

    // Initial run
    runStealthSetup();

    // Observe DOM changes
    const observer = new MutationObserver(runStealthSetup);
    observer.observe(document.body, { childList: true, subtree: true });

    // Alert to user
    setTimeout(() => {
        alert("소셜 로그인은 현재 지원되지 않습니다.\n\n기존에 소셜 계정으로 로그인하셨다면, 해당 계정에 연동된 이메일 주소와 비밀번호로 '이메일로 로그인'을 진행해주세요.");
    }, 200);
})();