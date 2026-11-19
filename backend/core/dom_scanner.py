import re
from typing import Any, Dict, Optional, Tuple


class DOMScanner:
    """Reads a portal page and maps its fields to stable semantic keys."""

    DETECTION_JS = r"""
    () => {
        const frameworks = [];
        if (window.__reactFiber || document.querySelector('[data-reactroot]') || window._reactRootContainer) frameworks.push('React');
        if (window.ng || document.querySelector('[ng-version]') || document.querySelector('[ng-app]')) frameworks.push('Angular');
        if (window.__vue__ || window.__vue_app__ || document.querySelector('[data-v-]')) frameworks.push('Vue');
        if (window.Sys && window.Sys.WebForms) frameworks.push('ASP.NET Ajax');
        if (document.getElementById('__VIEWSTATE')) frameworks.push('ASP.NET WebForms');
        if (window.Ext) frameworks.push('ExtJS');
        if (window.jQuery) frameworks.push('jQuery');
        if (frameworks.length === 0) frameworks.push('Standard HTML5');

        const isVisible = (el) => {
            if (!el) return false;
            if (el.checkVisibility) {
                try { return el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }); } catch (e) {}
            }
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
        };

        // Government portals ship an accessibility sidebar (font size,
        // contrast, oversized widget).  Its switches are not application
        // fields, and treating one as a form choice blocks the whole run.
        const ACCESSIBILITY_SELECTOR = [
            '[id*="accessib" i]', '[class*="accessib" i]',
            '[id*="a11y" i]', '[class*="a11y" i]',
            '[id*="acsb" i]', '[class*="acsb" i]',
            '[aria-label*="accessib" i]'
        ].join(',');
        const inAccessibilityWidget = (el) => {
            try { return Boolean(el.closest(ACCESSIBILITY_SELECTOR)); } catch (e) { return false; }
        };

        // A custom-styled checkbox/radio hides the real input and paints a
        // label or checkmark instead.  The control is still usable by a human,
        // so the agent must see it too; otherwise a consent box that gates the
        // submit button looks like it does not exist.
        const hasVisibleProxy = (el) => {
            const type = String(el.type || '').toLowerCase();
            if (type !== 'checkbox' && type !== 'radio') return false;
            let proxy = null;
            if (el.id) proxy = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
            if (!proxy) proxy = el.closest('label');
            if (!proxy && el.id) {
                const wrapper = el.parentElement;
                if (wrapper && wrapper.querySelector('label')) proxy = wrapper.querySelector('label');
            }
            return Boolean(proxy && isVisible(proxy));
        };

        const getLabel = (el) => {
            let labelText = '';
            if (el.id) {
                const labelEl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                if (labelEl) labelText += ' ' + labelEl.innerText;
            }
            const parentLabel = el.closest('label');
            if (parentLabel) labelText += ' ' + parentLabel.innerText;
            if (el.getAttribute('aria-label')) labelText += ' ' + el.getAttribute('aria-label');
            if (el.getAttribute('aria-labelledby')) {
                const ariaEl = document.getElementById(el.getAttribute('aria-labelledby'));
                if (ariaEl) labelText += ' ' + ariaEl.innerText;
            }
            // Bootstrap-style forms put a <label> beside the input in the
            // same wrapper without a "for" attribute.  Walk up a few levels
            // so a date field is called "Date of Birth", not "DD-MM-YYYY".
            // Only do this when no direct label was found, otherwise the
            // form's first label leaks into every later field.
            if (!labelText.trim()) {
                try {
                    let node = el.parentElement;
                    for (let depth = 0; node && depth < 3; depth += 1, node = node.parentElement) {
                        const ownLabel = node.querySelector(':scope > label, :scope > .form-label');
                        if (ownLabel) {
                            labelText += ' ' + (ownLabel.innerText || ownLabel.textContent || '');
                            break;
                        }
                        const previous = node.previousElementSibling;
                        if (previous) {
                            const tag = previous.tagName.toLowerCase();
                            const text = String(previous.innerText || previous.textContent || '').trim();
                            if (tag === 'label' || /form-label/.test(String(previous.className || ''))) {
                                if (text) {
                                    labelText += ' ' + text;
                                    break;
                                }
                            }
                        }
                    }
                } catch (e) {}
                const td = el.closest('td');
                if (td && td.previousElementSibling) labelText += ' ' + td.previousElementSibling.innerText;
            }
            // A placeholder or framework name is a format hint / machine
            // identifier, never the human-facing question.
            return labelText.replace(/\s+/g, ' ').trim();
        };

        const clickables = Array.from(document.querySelectorAll('button, a, input[type="button"], input[type="submit"], [role="button"], .btn, .loginButton'))
            .filter(el => !inAccessibilityWidget(el));
        const authHref = (href) => {
            const value = String(href || '').toLowerCase();
            if (!value) return null;
            if (/(?:resume|continue|track|status|saved[-_]?application)/.test(value)) return 'RESUME';
            if (/(?:^|\/)(?:signup|sign-up|register|registration|create-account|new-registration|account\/create)(?:\/|$|[?#])/.test(value)) return 'NEW_REGISTRATION';
            if (/(?:^|\/)(?:login|log-in|signin|sign-in)(?:\/|$|[?#])/.test(value)) return 'LOGIN';
            return null;
        };
        const entryType = (text, href, insideForm) => {
            const label = String(text || '').replace(/\s+/g, ' ').trim();
            if (!label || label.length > 140) return null;
            if (/forgot|help|instruction|manual|faq|guideline|privacy|terms|contact|download|notification|syllabus|result|admit\s*card/i.test(label)) return null;
            const pathType = authHref(href);
            // Government templates often wrap the register/login links in a
            // <form>.  Only form navigation controls are excluded; an anchor
            // with auth wording is still an entry path.
            if (insideForm && !pathType && /submit|save|next|continue|cancel|reset|back|previous|verify|send\s*otp|get\s*otp/i.test(label)) return null;
            if (pathType) return pathType;
            const resume = /resume|continue\s+(?:my\s+)?application|already\s+started|saved\s+application|track\s+(?:my\s+)?application|application\s+status/i.test(label);
            const register = /new\s*registration|account\s*creation|create\s*(?:an?\s*)?account|create\s+your\s+account|register(?:\s*here)?|registration\b|sign\s*up|signup|new\s*user|new\s*applicant|first[-\s]*time|get\s*started|\botr\b|apply\s*online/i.test(label);
            const login = /candidate\s*login|log\s*in|login|sign\s*in|signin|already\s*registered|returning\s*candidate|existing\s*(?:user|account|candidate)/i.test(label);
            if (resume && !register) return 'RESUME';
            if (register && login) return null;
            if (register) return 'NEW_REGISTRATION';
            if (login) return 'LOGIN';
            return null;
        };
        const gateways = [];
        for (const btn of clickables) {
            if (!isVisible(btn)) continue;
            const text = (btn.innerText || btn.value || btn.getAttribute('aria-label') || '').trim();
            const href = btn.getAttribute('href') || '';
            const insideForm = Boolean(btn.closest('form'));
            const gType = entryType(text, href, insideForm);
            if (gType) {
                const rect = btn.getBoundingClientRect();
                gateways.push({
                    text: text,
                    type: gType,
                    tagName: btn.tagName.toLowerCase(),
                    htmlType: String(btn.type || '').toLowerCase(),
                    role: (btn.getAttribute('role') || '').toLowerCase(),
                    id: btn.id || null,
                    name: btn.name || null,
                    className: btn.className || '',
                    href: href || null,
                    insideForm: insideForm,
                    visible: true,
                    interactable: !btn.disabled,
                    elementId: btn.getAttribute('data-fp-id') || null,
                    rect: { top: rect.top, left: rect.left, width: rect.width, height: rect.height }
                });
            }
        }

        // Landing pages rarely say "register" or "login"; they say "Online
        // Application Form for JEE (Main) 2027".  Those links are the real
        // next step, not an auth choice.  Collect them separately so the
        // orchestrator can follow one unambiguous application link instead of
        // stalling on a page that has no form fields.
        const applicationLinks = [];
        const applicationPattern = /online\s+application|application\s+form|apply\s+(?:online|now|here)|new\s+application|start\s+(?:a\s+)?(?:new\s+)?application|proceed\s+to\s+(?:apply|application)|fill\s+(?:the\s+)?application|registration\s+form|apply\s+for/i;
        const informationalPattern = /forgot|help|instruction|manual|faq|guideline|privacy|terms|contact|download|notification|syllabus|result|admit\s*card|answer\s*key|cut[-\s]*off|merit\s*list|clarification|inviting|public\s*notice|\bnotice\b|corrigendum|advertisement|press\s*release|information\s*bulletin|brochure|prospectus/i;
        const documentHrefPattern = /\.(?:pdf|docx?|xlsx?|zip|rar|jpe?g|png|gif)(?:[?#]|$)/i;
        const seenApplication = new Set();
        for (const btn of clickables) {
            if (!isVisible(btn)) continue;
            const text = (btn.innerText || btn.value || btn.getAttribute('aria-label') || '').trim();
            if (!text || text.length > 160) continue;
            if (informationalPattern.test(text)) continue;
            const href = btn.getAttribute('href') || '';
            // A PDF notification is not an application form.
            if (documentHrefPattern.test(href)) continue;
            const insideForm = Boolean(btn.closest('form'));
            // A form's submit button is not a landing-page link; an anchor
            // inside a form can still open the application.
            if (insideForm && !href) continue;
            // A link that is already an auth gateway is not an application link.
            if (entryType(text, href, insideForm)) continue;
            if (!applicationPattern.test(text) && !applicationPattern.test(href)) continue;
            const key = (href || text).toLowerCase().replace(/\s+/g, ' ').trim();
            if (seenApplication.has(key)) continue;
            seenApplication.add(key);
            const rect = btn.getBoundingClientRect();
            applicationLinks.push({
                text: text,
                tagName: btn.tagName.toLowerCase(),
                role: (btn.getAttribute('role') || '').toLowerCase(),
                id: btn.id || null,
                name: btn.name || null,
                className: btn.className || '',
                href: href || null,
                insideForm: insideForm,
                visible: true,
                interactable: !btn.disabled,
                elementId: btn.getAttribute('data-fp-id') || null,
                rect: { top: rect.top, left: rect.left, width: rect.width, height: rect.height }
            });
        }

        const inputs = [];
        const rawInputs = Array.from(document.querySelectorAll('input, select, textarea, [contenteditable="true"]'));
        let index = 0;
        for (const el of rawInputs) {
            if (el.type === 'hidden') continue;
            if (inAccessibilityWidget(el)) continue;
            const visible = isVisible(el);
            if (!visible && !hasVisibleProxy(el)) continue;
            const rect = el.getBoundingClientRect();
            const tag = el.tagName.toLowerCase();
            const type = (el.type || (tag === 'select' ? 'select' : 'text')).toLowerCase();
            let options = [];
            if (tag === 'select') {
                options = Array.from(el.options).map(o => ({ text: o.text.trim(), value: o.value })).filter(o => o.text && o.value);
            }
            inputs.push({
                index: index++,
                tagName: tag,
                type: type,
                id: el.id || '',
                name: el.name || '',
                label: getLabel(el),
                value: el.value || el.innerText || '',
                checked: el.checked || false,
                visible: Boolean(visible || hasVisibleProxy(el)),
                readOnly: Boolean(el.readOnly),
                disabled: Boolean(el.disabled),
                maxLength: Number(el.maxLength || 0),
                required: el.required || el.getAttribute('aria-required') === 'true' || getLabel(el).includes('*'),
                placeholder: el.placeholder || '',
                options: options,
                selectedText: tag === 'select' && el.selectedIndex >= 0 ? el.options[el.selectedIndex].text : '',
                elementId: el.getAttribute('data-fp-id') || null,
                rect: { top: rect.top, left: rect.left, width: rect.width, height: rect.height }
            });
        }

        const nextButtons = [];
        for (const btn of clickables) {
            if (!isVisible(btn)) continue;
            const text = (btn.innerText || btn.value || btn.getAttribute('aria-label') || '').trim();
            const href = btn.getAttribute('href') || '';
            const insideForm = Boolean(btn.closest('form'));
            const nextish = /save\s*&\s*next|save\s*and\s*next|proceed|continue|next\s*step|\bnext\b|submit|log\s*in|sign\s*in|register|create\s*(?:an?\s*)?account|account\s*creation|verify|verification|confirm|send\s*otp|get\s*otp|apply|pay|checkout|finish|complete(?:\s+.*)?|save|update|allow|authori[sz]e|approve|agree|accept|authenticate|validate|forward|redirect|done|ok/i.test(text);
            const isNegative = /forgot|help|instruction|manual|faq|guideline|privacy|terms|download|notification|syllabus|result|admit\s*card|back|previous|cancel|close|abort|reset|clear|exit|logout|sign\s*out/i.test(text);
            if (isNegative) continue;
            // A login/signup navigation link is an entry path, never the
            // button that advances the current form.
            if (authHref(href)) continue;
            const isSubmitControl = ['button', 'input'].includes(btn.tagName.toLowerCase())
                || /submit|btn-next|btn-main|next|primary/i.test(String(btn.className || ''))
                || /submit|next|btn-main/i.test(String(btn.id || ''));
            if (entryType(text, href, insideForm) && !insideForm && !isSubmitControl) continue;
            if (!nextish && !isSubmitControl && !insideForm) continue;
            const rect = btn.getBoundingClientRect();
            nextButtons.push({
                text: text,
                tagName: btn.tagName.toLowerCase(),
                type: String(btn.type || '').toLowerCase(),
                role: (btn.getAttribute('role') || '').toLowerCase(),
                id: btn.id || null,
                name: btn.name || null,
                className: btn.className || '',
                href: href || null,
                insideForm: insideForm,
                visible: true,
                interactable: !btn.disabled,
                elementId: btn.getAttribute('data-fp-id') || null,
                rect: { top: rect.top, left: rect.left, width: rect.width, height: rect.height }
            });
        }

        const getNearbyText = (el) => {
            let text = '';
            let node = el;
            for (let i = 0; i < 4 && node; i++) {
                text += ' ' + (node.innerText || node.textContent || '');
                node = node.parentElement;
            }
            const prev = el.previousElementSibling;
            const next = el.nextElementSibling;
            if (prev) text += ' ' + (prev.innerText || prev.textContent || '');
            if (next) text += ' ' + (next.innerText || next.textContent || '');
            return text.replace(/\s+/g, ' ').trim().slice(0, 240);
        };

        const hasNearbyTextInput = (el) => {
            // NEVER walk up to the root <form> or <body> without a captcha marker.
            // On ASP.NET portals (e.g. JEE), the whole page is wrapped in <form id="aspnetForm">.
            let container = el.parentElement;
            let depth = 0;
            let foundSpecificMarker = false;
            while (container && depth < 5) {
                const marker = `${container.id || ''} ${container.className || ''}`.toLowerCase();
                if (/captcha|turnstile|recaptcha|h-captcha|security[-\s]?code|security[-\s]?pin/.test(marker)) {
                    foundSpecificMarker = true;
                    break;
                }
                if (container.tagName === 'FORM' || container.tagName === 'BODY') break;
                container = container.parentElement;
                depth++;
            }
            if (!container) return false;
            const inputs = Array.from(container.querySelectorAll('input[type="text"], input:not([type]), textarea')).filter(isVisible);
            return inputs.some(inp => {
                const text = `${inp.id || ''} ${inp.name || ''} ${inp.placeholder || ''} ${getNearbyText(inp)}`.toLowerCase();
                return /captcha|security[-\s]?code|security[-\s]?pin|enter\s*(the\s*)?code|code\s*shown/i.test(text);
            });
        };

        const isLogoOrBanner = (el) => {
            const str = `${el.id || ''} ${el.className || ''} ${el.getAttribute('src') || ''} ${el.getAttribute('alt') || ''}`.toLowerCase();
            return /logo|banner|header|emblem|national|ministry|gov|brand|icon|footer|avatar|photo/i.test(str);
        };

        const captchaElements = [];
        const seenCaptcha = new Set();
        let capIndex = 0;
        const addCaptcha = (el, kind, prompt) => {
            const key = (el.id || '') + '|' + el.tagName + '|' + (el.getAttribute('src') || '') + '|' + kind;
            if (seenCaptcha.has(key)) return;
            seenCaptcha.add(key);
            const capId = 'fp-cap-' + (++capIndex);
            try { el.setAttribute('data-fp-captcha-target', capId); } catch (_) {}
            const rect = el.getBoundingClientRect();
            captchaElements.push({
                tagName: el.tagName.toLowerCase(),
                kind: kind,
                id: el.id || null,
                name: el.name || null,
                captchaTargetId: capId,
                prompt: (prompt || '').slice(0, 240),
                src: (el.getAttribute('src') || '').slice(0, 300),
                elementId: el.getAttribute('data-fp-id') || null,
                rect: { top: rect.top, left: rect.left, width: rect.width, height: rect.height }
            });
        };

        // Image/canvas text challenges, Cloudflare Turnstile, reCAPTCHA,
        // hCaptcha, sliders and drag puzzles.  Classification is only used to
        // give the human better instructions; no challenge is solved here.
        const captchaCandidates = Array.from(document.querySelectorAll(
            'img, canvas, iframe, [id*="captcha" i], [class*="captcha" i], '
            + '[class*="turnstile" i], [id*="turnstile" i], '
            + '[class*="g-recaptcha" i], [class*="h-captcha" i], [data-sitekey]'
        ));
        for (const el of captchaCandidates) {
            if (!isVisible(el)) continue;
            const tagName = el.tagName.toLowerCase();
            const idLower = String(el.id || '').toLowerCase();
            const classLower = String(el.className || '').toLowerCase();
            const src = String(el.getAttribute('src') || '').toLowerCase();
            const combined = `${idLower} ${classLower} ${src} ${getNearbyText(el).toLowerCase()}`;
            // A wrapper such as <div class="captcha-box"> is not the challenge
            // itself.  Skip it when it contains the real widget; otherwise the
            // wrapper is reported as an unknown challenge and forces a live
            // handoff even for a simple text CAPTCHA.
            if (['div', 'section', 'span', 'form', 'fieldset', 'label', 'p'].includes(tagName)) {
                const widgetMarker = /g-recaptcha|h-captcha|cf-turnstile|turnstile|recaptcha/.test(`${idLower} ${classLower}`);
                const hasWidget = el.querySelector(
                    'canvas, img, iframe, input, textarea, [data-sitekey], .g-recaptcha, .h-captcha, .cf-turnstile'
                );
                if (hasWidget && !widgetMarker) continue;
            }
            let kind = null;
            if (tagName === 'iframe' || /turnstile|recaptcha|hcaptcha|cloudflare/.test(combined)) {
                kind = 'interactive';
            } else if (/slider|slide\s*to|drag\s*the|drag\s*and\s*drop|puzzle/.test(combined)) {
                kind = /drag/.test(combined) ? 'drag' : 'slider';
            } else if (tagName === 'canvas' || tagName === 'img') {
                if (isLogoOrBanner(el)) continue;
                if (idLower.includes('captcha') || classLower.includes('captcha') || src.includes('captcha')) {
                    kind = hasNearbyTextInput(el) ? 'text' : 'unknown';
                } else if (hasNearbyTextInput(el)) {
                    kind = 'text';
                }
            }
            if (!kind && (idLower.includes('captcha') || classLower.includes('captcha') || src.includes('captcha'))) {
                // A text field whose name/id mentions captcha is where the
                // human types the answer; it is not an interactive widget.
                kind = ['input', 'textarea'].includes(tagName) ? 'text' : 'unknown';
            }
            if (kind) {
                const rect = el.getBoundingClientRect();
                if (rect.width > 20 && rect.height > 12) {
                    addCaptcha(el, kind, getNearbyText(el));
                }
            }
        }

        // Some portals show a text prompt instead of an image.
        for (const el of document.querySelectorAll('input[id*="captcha" i], input[name*="captcha" i]')) {
            if (!isVisible(el)) continue;
            if (captchaElements.some((item) => item.id && item.id === el.id)) continue;
            const surrounding = getNearbyText(el).toLowerCase();
            if (surrounding.includes('captcha') || surrounding.includes('security code') || surrounding.includes('enter the code')) {
                addCaptcha(el, 'text', getNearbyText(el));
            }
        }

        const errors = [];
        const errorNodes = Array.from(document.querySelectorAll('.error, .alert-danger, .text-danger, .invalid-feedback, [role="alert"], .mat-error, .field-validation-error, span[style*="red"], font[color="red"]'));
        for (const node of errorNodes) {
            if (!isVisible(node)) continue;
            const txt = (node.innerText || '').trim();
            if (txt && !txt.includes('* indicates') && !txt.includes('Password must') && txt.length > 3) errors.push(txt);
        }

        const bodyText = (document.body && document.body.innerText ? document.body.innerText : '').replace(/\s+/g, ' ').trim();
        const lowerBody = bodyText.toLowerCase();
        const fileInputs = Array.from(document.querySelectorAll('input[type="file"]'))
            .filter(isVisible)
            .map((el) => {
                const rect = el.getBoundingClientRect();
                return {
                    id: el.id || '',
                    name: el.name || '',
                    label: getLabel(el),
                    accept: el.accept || '',
                    capture: el.getAttribute('capture') || '',
                    hasFile: Boolean(el.files && el.files.length),
                    elementId: el.getAttribute('data-fp-id') || null,
                    rect: { top: rect.top, left: rect.left, width: rect.width, height: rect.height }
                };
            });
        const livePhotoRequired = /live\s*(photo|photograph|picture)|webcam|camera|capture\s*(photo|image)|liveness/.test(lowerBody)
            && (fileInputs.length > 0 || !!document.querySelector('video'));
        const otpInputs = Array.from(document.querySelectorAll('input'))
            .filter((el) => isVisible(el) && /otp|one[-\s]?time|verification\s*(?:code|pin)|auth(entication)?\s*code|passcode|access\s*code/i.test(
                `${el.id || ''} ${el.name || ''} ${el.placeholder || ''} ${getLabel(el) || ''}`
            ))
            .map((el) => ({
                id: el.id || '',
                name: el.name || '',
                label: getLabel(el),
                type: (el.type || 'text').toLowerCase(),
                elementId: el.getAttribute('data-fp-id') || null
            }));
        const formAction = document.querySelector('form') ? (document.querySelector('form').getAttribute('action') || '') : '';
        const paymentWords = ['application fee', 'pay fee', 'payment', 'checkout', 'net banking', 'debit card', 'credit card', 'upi', 'proceed to pay'];
        const paymentSignals = paymentWords.filter(w => lowerBody.includes(w)).length;
        const activeSection = document.querySelector('.form-section.active, .section.active, [data-section].active');
        const heading = document.querySelector('.form-section.active h2, .section.active h2, h1, h2');
        const paymentButton = Array.from(document.querySelectorAll('button, input[type="submit"], a[role="button"]'))
            .filter(isVisible)
            .find(b => {
                const text = (b.innerText || b.value || '').trim();
                const isPayment = /\b(pay|payment|checkout)\b/i.test(text);
                const isReview = /pre[-\s]*payment|review|back|previous/i.test(text);
                return isPayment && !isReview;
            });
        return {
            title: document.title,
            url: window.location.href,
            frameworks: frameworks,
            gateways: gateways,
            applicationLinks: applicationLinks,
            inputs: inputs,
            nextButtons: nextButtons,
            captchaElements: captchaElements,
            errors: errors,
            visibleText: bodyText.slice(0, 4000),
            loading: /loading|please\s+wait|processing|initiali[sz]ing|fetching/i.test(lowerBody)
                && !document.querySelector('input:not([type="hidden"]), select, textarea'),
            paymentSignals: paymentSignals,
            hasPaymentButton: !!paymentButton,
            activeSectionId: activeSection ? (activeSection.id || '') : '',
            stepHeading: heading ? (heading.innerText || '').trim().slice(0, 160) : '',
            formCount: document.querySelectorAll('form').length,
            formAction: formAction.slice(0, 500),
            fileInputs: fileInputs,
            livePhotoRequired: livePhotoRequired,
            otpInputs: otpInputs
        };
    }
    """

    EXTRACT_VALUES_JS = r"""
    (includeHidden = false) => {
        const isVisible = (el) => {
            if (!el) return false;
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
        };
        const getLabel = (el) => {
            let text = '';
            if (el.id) {
                const labelEl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                if (labelEl) text += ' ' + labelEl.innerText;
            }
            const parent = el.closest('label');
            if (parent) text += ' ' + parent.innerText;
            if (el.getAttribute('aria-label')) text += ' ' + el.getAttribute('aria-label');
            if (el.name) text += ' ' + el.name;
            return text.replace(/\s+/g, ' ').trim();
        };
        // Government portals ship an accessibility sidebar (font size,
        // contrast, oversized widget).  Its switches are not application
        // fields, and treating one as a form choice blocks the whole run.
        const ACCESSIBILITY_SELECTOR = [
            '[id*="accessib" i]', '[class*="accessib" i]',
            '[id*="a11y" i]', '[class*="a11y" i]',
            '[id*="acsb" i]', '[class*="acsb" i]',
            '[aria-label*="accessib" i]'
        ].join(',');
        const inAccessibilityWidget = (el) => {
            try { return Boolean(el.closest(ACCESSIBILITY_SELECTOR)); } catch (e) { return false; }
        };

        // A custom-styled checkbox/radio hides the real input and paints a
        // label or checkmark instead.  The control is still usable by a human,
        // so the agent must see it too; otherwise a consent box that gates the
        // submit button looks like it does not exist.
        const hasVisibleProxy = (el) => {
            const type = String(el.type || '').toLowerCase();
            if (type !== 'checkbox' && type !== 'radio') return false;
            let proxy = null;
            if (el.id) {
                proxy = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
            }
            if (!proxy) proxy = el.closest('label');
            if (!proxy && el.id) {
                const parent = el.parentElement;
                if (parent && parent.querySelector('label')) proxy = parent.querySelector('label');
            }
            return !!(proxy && isVisible(proxy));
        };
        return Array.from(document.querySelectorAll('input, select, textarea, [contenteditable="true"]'))
            .filter(el => el.type !== 'hidden' && !inAccessibilityWidget(el)
                && (includeHidden || isVisible(el) || hasVisibleProxy(el)))
            .map((el, index) => ({
                index: index,
                id: el.id || '',
                name: el.name || '',
                label: getLabel(el),
                type: (el.type || el.tagName.toLowerCase()).toLowerCase(),
                value: el.type === 'file' ? (el.files && el.files.length ? el.files[0].name : '') : (el.value || el.innerText || ''),
                checked: !!el.checked,
                visible: Boolean(isVisible(el) || hasVisibleProxy(el)),
                fileCount: el.type === 'file' && el.files ? el.files.length : 0,
                elementId: el.getAttribute('data-fp-id') || null,
                selectedText: el.tagName && el.tagName.toLowerCase() === 'select' && el.selectedIndex >= 0 ? el.options[el.selectedIndex].text : ''
            }));
    }
    """

    _active_blueprint: Optional[Any] = None

    @classmethod
    def set_active_blueprint(cls, blueprint: Optional[Any]) -> None:
        """Ground DOM classification in certified examination blueprint specs."""
        cls._active_blueprint = blueprint

    @classmethod
    def get_active_blueprint(cls) -> Optional[Any]:
        return cls._active_blueprint

    @classmethod
    def classify_field(cls, field_meta: Dict[str, Any], blueprint: Optional[Any] = None) -> Tuple[Optional[str], bool]:
        """Map a portal input to a semantic key and a verify/confirm flag."""
        active_bp = blueprint or cls._active_blueprint
        field_type = str(field_meta.get("type", "") or "").lower()
        if field_type in {"radio", "checkbox"}:
            # A radio/checkbox label is the option text, not the question.  On
            # the JEE instruction page the option "Indian Nationals ... Aadhaar"
            # would otherwise be filled with an Aadhaar number.  Trust only the
            # machine name/id, and only for genuine choice concepts.
            machine = " ".join(
                str(field_meta.get(k, "") or "") for k in ("id", "name")
            ).lower()
            flabel = str(field_meta.get("label", "") or "").lower()
            if re.search(r"rbloption", machine) and not re.search(r"declaration", machine):
                return ("nationality", False)
            if re.search(
                r"same\s*as\s*(?:present|permanent|correspondence)|chk(?:same|address)|"
                r"permanent.*same.*present|present.*same.*permanent|पत्राचार.*स्थायी|स्थायी.*वर्तमान",
                f"{machine} {flabel}",
            ):
                return ("same_as_permanent", False)
            if not re.search(
                r"gender|\bsex\b|category|caste|nationality|religion|marital|"
                r"disab|pwd|ex[-\s]?serviceman|domicile|state",
                machine,
            ):
                return (None, False)
            combined = machine
        else:
            combined = " ".join(
                str(field_meta.get(k, "") or "")
                for k in ("id", "name", "label", "placeholder", "aria_label")
            ).lower()
        is_verify = bool(re.search(r"\bconfirm|verify|re-?enter|repeat", combined))

        # Grounded Blueprint Matching (Official Exam Bulletin Ground Truth)
        if active_bp is not None:
            fid = str(field_meta.get("id", "") or "").strip().lower()
            fname = str(field_meta.get("name", "") or "").strip().lower()
            flabel = str(field_meta.get("label", "") or "").strip().lower()

            for spec_id, spec in getattr(active_bp, "all_fields_by_id", {}).items():
                spec_id_lower = spec_id.lower()
                if (fid and fid == spec_id_lower) or (fname and fname == spec_id_lower):
                    return (spec.canonical_concept, bool(spec.auto_reused_from or "verify" in spec_id_lower or is_verify))

                if flabel and spec.label_en:
                    spec_en_lower = spec.label_en.lower()
                    if spec_en_lower in flabel and len(spec_en_lower) >= 4:
                        if "father" in spec_en_lower and re.search(r"mother|माता", flabel):
                            continue
                        if "mother" in spec_en_lower and not re.search(r"mother|माता", flabel):
                            continue
                        if "permanent" in spec_en_lower and re.search(r"present|वर्तमान", flabel):
                            continue
                        if "present" in spec_en_lower and re.search(r"permanent|स्थायी", flabel):
                            continue
                        return (spec.canonical_concept, bool(spec.auto_reused_from or "verify" in spec_id_lower or is_verify))

        # Never fill one-time codes or CAPTCHA answers from the vault.  They
        # are handled by an explicit user checkpoint.
        if re.search(r"otp|one[-\s]?time\s*(password|code)|verification\s*code|auth(entication)?\s*code", combined):
            return (None, False)
        if re.search(r"captcha|security\s*check|enter\s*(the\s*)?code\s*(shown|above)", combined):
            return (None, False)

        # A password box is a credential, never a profile fact.  Only a portal
        # account password has a stored value; an identity-provider PIN (the
        # DigiLocker page names its box ``passwordmobile``) must not be filled
        # with a phone number, and a bare "pin" is not a postal code here.
        if field_type == "password":
            if re.search(r"password|pwd|passcode", combined) and not re.search(
                r"\bpin\b|otp|aadhaar|aadhar|uidai", combined
            ):
                return ("account_password", is_verify)
            return (None, False)

        # Identity disambiguation
        # Check mother / माता first. In Indian forms, labels are often bilingual:
        # "माता / अभिभावक का नाम (Mother / Guardian Name)" vs "पिता / अभिभावक का नाम (Father / Guardian Name)".
        # "guardian" appears in both! Mother must be checked first, or father must explicitly exclude mother.
        if re.search(r"mother|माता|mom|maternal", combined):
            return ("verify_mother_name" if is_verify else "mother_name", is_verify)
        if re.search(r"father|पिता|dad|paternal", combined):
            return ("verify_father_name" if is_verify else "father_name", is_verify)
        if re.search(r"spouse|husband|wife|पति|पत्नी", combined):
            return ("spouse_name", is_verify)
        if re.search(r"guardian|अभिभावक", combined) and not re.search(r"mother|माता", combined):
            return ("verify_father_name" if is_verify else "father_name", is_verify)
        if re.search(r"candidate\s*name|applicant\s*name|full\s*name|student\s*name|your\s*name|अभ्यर्थी\s*का\s*नाम", combined) or (
            re.search(r"\bname\b", combined) and not re.search(r"board|school|college|user|father|mother|guardian|spouse|husband|wife|bank|holder|matric|10th|12th|पिता|माता|अभिभावक|पति|पत्नी", combined)
        ):
            return ("verify_full_name" if is_verify else "full_name", is_verify)

        if re.search(r"\bdob\b|birth|date_of_birth|dateofbirth|जन्म", combined):
            return ("dob", is_verify)
        if re.search(r"gender|\bsex\b|लिंग", combined):
            return ("gender", is_verify)
        if re.search(r"marital|वैवाहिक", combined):
            return ("marital_status", is_verify)
        if re.search(r"religion|धार्मिक|धर्म", combined):
            return ("religion", is_verify)
        if re.search(r"nationality|नागरिकता|citizen", combined):
            return ("nationality", is_verify)

        # Reservation / domicile
        if re.search(r"sub[-\s]?caste|subcaste|उपजाति", combined):
            return ("sub_caste", is_verify)
        if re.search(r"category|social_status|सामाजिक\s*वर्ग|श्रेणी|आरक्षण", combined) or (
            re.search(r"\bcaste\b|community", combined) and not re.search(r"sub[-\s]?caste", combined)
        ):
            return ("category", is_verify)
        if re.search(r"domicile|state_of_origin|residential_state|मूल\s*निवास", combined):
            return ("domicile_state", is_verify)
        if re.search(r"disab|differently\s*abled|pwd|दिव्यांग", combined) and not re.search(r"scribe", combined):
            return ("is_differently_abled", is_verify)
        if re.search(r"ex[-\s]?serviceman|भूतपूर्व\s*सैनिक", combined):
            return ("is_ex_serviceman", is_verify)

        # Contact disambiguation: Alternate/Secondary MUST be checked before Primary
        if re.search(r"alternate.*(mobile|phone)|secondary.*(mobile|phone)|emergency.*(mobile|phone)|parent.*(mobile|phone)|guardian.*(mobile|phone)", combined):
            return ("alternate_mobile", is_verify)
        if re.search(r"mobile|phone|contact_no|cell|whatsapp|दूरभाष|मोबाइल", combined):
            return ("mobile", is_verify)
        if re.search(r"alternate.*email|secondary.*email|parent.*email", combined):
            return ("alternate_email", is_verify)
        if re.search(r"email|mail_id|e-mail|ईमेल", combined):
            return ("confirm_email" if is_verify else "email", is_verify)

        # Identifiers
        if re.search(r"aadhaar|aadhar|uidai|आधार", combined):
            return ("aadhaar_number", is_verify)
        if re.search(r"apaar", combined):
            return ("apaar_id", is_verify)
        if re.search(r"digilocker", combined):
            return ("digilocker_id", is_verify)
        if re.search(r"height|ऊंचाई", combined):
            return ("height_cm", is_verify)
        if re.search(r"chest|सीना", combined):
            return ("chest_cm", is_verify)
        if re.search(r"reg_id|registration\s*(id|no|number)|reg_no|otr|application\s*(id|no|number)", combined):
            return ("registration_id", is_verify)
        if re.search(r"password|pwd|passcode|पासवर्ड", combined):
            return ("account_password", is_verify)

        # Address disambiguation: Present/Correspondence/Current FIRST
        is_present = bool(re.search(r"present|correspondence|current|local|communication|temporary|पत्राचार|वर्तमान", combined))
        if is_present:
            if re.search(r"pincode|pin_code|postal_code|zip|पिन", combined) and not re.search(r"security|mpin", combined):
                return ("present_pincode", is_verify)
            if re.search(r"district|ज़िला|जिला", combined):
                return ("present_district", is_verify)
            if re.search(r"\bstate\b|राज्य", combined) and not re.search(r"statement", combined):
                return ("present_state", is_verify)
            if re.search(r"address\s*(line)?\s*2|landmark|locality|colony|street|area", combined):
                return ("present_address_line_2", is_verify)
            if re.search(r"address|permanent|residential|house|flat|premises|पता", combined):
                return ("present_address_line_1", is_verify)

        # Permanent address
        if re.search(r"pincode|pin_code|postal_code|zip|पिन", combined) and not re.search(r"security|mpin", combined):
            return ("pincode", is_verify)
        if re.search(r"village|town|city|गाँव|शहर", combined):
            return ("village_town_city", is_verify)
        if re.search(r"district|ज़िला|जिला", combined):
            return ("district", is_verify)
        if re.search(r"\bstate\b|राज्य", combined) and not re.search(r"statement|domicile", combined):
            return ("state", is_verify)
        if re.search(r"address\s*(line)?\s*2|landmark|locality|colony|street|area", combined):
            return ("address_line_2", is_verify)
        if re.search(r"address|permanent_address|residential|house|flat|premises|पता", combined):
            return ("address_line_1", is_verify)

        # Identification marks
        if re.search(r"mark\s*2", combined):
            return ("identification_mark_2", is_verify)
        if re.search(r"mark\s*1|identification_mark|mole|scar", combined):
            return ("identification_mark_1", is_verify)

        # File uploads (before academic text fields)
        if field_type == "file":
            if re.search(r"photo|photograph|pic|image", combined):
                return ("photo_upload", is_verify)
            if re.search(r"sign|signature|\bsig\b|sig_", combined):
                return ("signature_upload", is_verify)
            if re.search(r"10th|matric|marksheet", combined):
                return ("matric_cert_upload", is_verify)
            return (None, False)

        # Intermediate / 12th (must be checked before matric)
        if re.search(r"intermediate|12th|senior\s*secondary|higher\s*secondary|plus\s*two|\bpuc\b", combined):
            if re.search(r"roll|seat", combined):
                return ("intermediate_roll_number", is_verify)
            if re.search(r"board", combined):
                return ("intermediate_board", is_verify)
            if re.search(r"stream|subject|faculty", combined):
                return ("intermediate_stream", is_verify)
            if re.search(r"year|passing", combined):
                return ("intermediate_passing_year", is_verify)
            if re.search(r"cgpa|gpa", combined):
                return ("intermediate_percentage", is_verify)
            if re.search(r"total\s*marks", combined):
                return ("intermediate_total_marks", is_verify)
            if re.search(r"obtained|marks|percentage", combined):
                return ("intermediate_percentage", is_verify)
            if re.search(r"college|school", combined):
                return ("intermediate_college_name", is_verify)
            if re.search(r"certificate", combined):
                return ("intermediate_certificate_number", is_verify)

        # Graduation
        if re.search(r"\b(graduat\w*|bachelor\w*|b\.?\s*(sc|com|a|tech|e)|degree|university)\b", combined):
            if re.search(r"roll|enrol", combined):
                return ("graduation_roll_number", is_verify)
            if re.search(r"university|college|institute", combined):
                return ("graduation_university", is_verify)
            if re.search(r"year|passing", combined):
                return ("graduation_passing_year", is_verify)
            if re.search(r"cgpa|gpa|percentage|marks", combined):
                return ("graduation_percentage", is_verify)
            if re.search(r"degree|course|stream", combined):
                return ("graduation_degree_name", is_verify)

        # Matric / 10th
        if re.search(r"10th|matric|high\s*school|secondary\s*school", combined):
            if re.search(r"roll|seat", combined):
                return ("matric_roll_number", is_verify)
            if re.search(r"board", combined):
                return ("matric_board", is_verify)
            if re.search(r"year|passing", combined):
                return ("matric_passing_year", is_verify)
            if re.search(r"cgpa|gpa", combined):
                return ("matric_cgpa", is_verify)
            if re.search(r"total\s*marks", combined):
                return ("matric_total_marks", is_verify)
            if re.search(r"obtained|marks|percentage", combined):
                return ("matric_percentage", is_verify)
            if re.search(r"school", combined):
                return ("matric_school_name", is_verify)
            if re.search(r"certificate", combined):
                return ("matric_certificate_number", is_verify)

        # Generic custom fields that portals sometimes add.
        if re.search(r"mother\s*tongue|language", combined):
            return ("mother_tongue", is_verify)
        if re.search(r"employment|occupation", combined):
            return ("employment_status", is_verify)
        if re.search(r"criminal", combined):
            return ("criminal_case_pending", is_verify)
        if re.search(r"debarred", combined):
            return ("debarred_from_exam", is_verify)

        return (None, False)

    INJECTION_JS = r"""
    ([targetMeta, value]) => {
        let el = null;
        if (targetMeta.id) el = document.getElementById(targetMeta.id);
        if (!el && targetMeta.name) {
            el = document.querySelector(`[name="${CSS.escape(targetMeta.name)}"]`);
        }
        if (!el && targetMeta.index !== undefined) {
            const raw = Array.from(document.querySelectorAll('input, select, textarea, [contenteditable="true"]')).filter(e => {
                if (e.type === 'hidden') return false;
                const rect = e.getBoundingClientRect();
                const style = window.getComputedStyle(e);
                return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
            });
            el = raw[targetMeta.index];
        }
        if (!el) return { success: false, reason: 'Field not found on the page' };
        if (el.type === 'file') return { success: false, reason: 'File fields need a separate upload step' };

        const norm = (v) => String(v == null ? '' : v).toLowerCase().replace(/[^a-z0-9]/g, '');
        const targetRaw = String(value == null ? '' : value).trim();
        const target = norm(targetRaw);

        const selectLabel = (node) => {
            if (!node) return '';
            let text = '';
            if (node.id) {
                const l = document.querySelector(`label[for="${CSS.escape(node.id)}"]`);
                if (l) text += ' ' + l.innerText;
            }
            const p = node.closest('label');
            if (p) text += ' ' + p.innerText;
            return text.replace(/\s+/g, ' ').trim();
        };

        if (el.tagName.toLowerCase() === 'select') {
            const options = Array.from(el.options);
            let match = options.find(o => norm(o.value) === target || norm(o.text) === target);
            if (!match) match = options.find(o => norm(o.text).includes(target) || target.includes(norm(o.text)));
            if (!match && target === 'obcncl') {
                match = options.find(o => norm(o.text).includes('obc') && norm(o.text).includes('ncl'));
            }
            if (!match && ['ur', 'general', 'unreserved'].includes(target)) {
                match = options.find(o => norm(o.text).includes('general') || norm(o.text).includes('unreserved') || norm(o.text) === 'ur');
            }
            if (!match && ['yes', 'no'].includes(target)) {
                match = options.find(o => norm(o.text) === target);
            }
            if (!match) return { success: false, reason: 'No matching option', options: options.map(o => o.text) };
            el.value = match.value;
            el.selectedIndex = match.index;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return { success: true, method: 'select', value: match.value, text: match.text };
        }

        if (el.type === 'radio') {
            const group = el.name
                ? Array.from(document.querySelectorAll(`input[type="radio"][name="${CSS.escape(el.name)}"]`))
                : [el];
            let match = group.find(r => norm(r.value) === target);
            if (!match) match = group.find(r => norm(selectLabel(r)).includes(target));
            if (!match && ['yes', 'no'].includes(target)) {
                match = group.find(r => norm(r.value) === target || norm(selectLabel(r)) === target);
            }
            if (!match) return { success: false, reason: 'No matching radio option' };
            if (!match.checked) {
                try { match.click(); } catch (e) {}
            }
            if (!match.checked) {
                let proxy = null;
                if (match.id) proxy = document.querySelector(`label[for="${CSS.escape(match.id)}"]`);
                if (!proxy) proxy = match.closest('label');
                if (!proxy && match.parentElement) proxy = match.parentElement.querySelector('label');
                if (proxy) {
                    try { proxy.click(); } catch (e) {}
                }
            }
            if (!match.checked) {
                match.checked = true;
                match.dispatchEvent(new Event('input', { bubbles: true }));
                match.dispatchEvent(new Event('change', { bubbles: true }));
            }
            return { success: true, method: 'radio', value: match.value };
        }

        if (el.type === 'checkbox') {
            const wantsNo = ['no', 'false', '0', 'unchecked'].includes(target);
            const targetState = !wantsNo;
            if (el.checked !== targetState) {
                try { el.click(); } catch (e) {}
            }
            if (el.checked !== targetState) {
                let proxy = null;
                if (el.id) proxy = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                if (!proxy) proxy = el.closest('label');
                if (!proxy && el.parentElement) proxy = el.parentElement.querySelector('label');
                if (proxy) {
                    try { proxy.click(); } catch (e) {}
                }
            }
            if (el.checked !== targetState) {
                el.checked = targetState;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }
            return { success: true, method: 'checkbox', value: el.checked };
        }

        let finalValue = targetRaw;
        if (el.type === 'date') {
            const dmy = targetRaw.match(/^(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{4})$/);
            if (dmy) finalValue = `${dmy[3]}-${dmy[2].padStart(2, '0')}-${dmy[1].padStart(2, '0')}`;
        }

        el.focus();
        if (el.isContentEditable) {
            el.innerText = finalValue;
        } else {
            const proto = window.HTMLInputElement.prototype;
            const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
            if (descriptor && descriptor.set) descriptor.set.call(el, finalValue);
            else el.value = finalValue;
        }
        try {
            el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: finalValue }));
        } catch (e) {
            el.dispatchEvent(new Event('input', { bubbles: true }));
        }
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.dispatchEvent(new Event('blur', { bubbles: true }));
        return { success: true, method: el.type === 'date' ? 'date' : 'input', value: finalValue };
    }
    """

    # ------------------------------------------------------------------
    # Blueprint scanner v2
    #
    # This pass is deliberately separate from DETECTION_JS.  It stamps every
    # meaningful element with a per-scan id, records a nested tree and returns
    # the metadata the action resolver needs.  DETECTION_JS then runs against
    # the same DOM and its legacy lists are enriched with those ids.
    # ------------------------------------------------------------------

    STRUCTURE_JS = r"""
    (frameId = "main") => {
        const MAX_ELEMENTS = 6000;
        const MAX_TEXT = 4000;
        const MAX_OPTIONS = 200;
        const scanId = "s" + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
        let counter = 0;
        let omitted = 0;
        const elements = [];
        const byId = new Map();
        const roots = [];
        const scanStarted = new Date().toISOString();

        const normalize = (value) => String(value == null ? "" : value).replace(/\s+/g, " ").trim();
        const truncate = (value, limit = MAX_TEXT) => {
            const text = normalize(value);
            return text.length > limit ? text.slice(0, limit) + "..." : text;
        };
        const attr = (el, name) => {
            try { return el && el.getAttribute ? el.getAttribute(name) : null; } catch (e) { return null; }
        };
        const cssEscape = (value) => {
            try {
                if (window.CSS && CSS.escape) return CSS.escape(String(value));
            } catch (e) {}
            return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
        };
        const cssAttr = (value) => String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
        const xpathString = (value) => {
            const text = String(value);
            if (!text.includes("'")) return "'" + text + "'";
            if (!text.includes('"')) return '"' + text + '"';
            return "concat('" + text.replace(/'/g, "', \"'\", '") + "')";
        };
        const stableId = (value) => {
            const id = String(value || "");
            if (!id || id.length > 80) return false;
            if (/^[a-f0-9]{8,}$/i.test(id)) return false;
            if (/^:r[0-9a-z]+:/i.test(id)) return false;
            if (/^(mui|radix|react|ember|ext-gen|yui_|gwt-uid|rc-|ant-)/i.test(id)) return false;
            if (/\d{6,}/.test(id)) return false;
            return true;
        };
        const rootOf = (el) => {
            try { return el.getRootNode(); } catch (e) { return document; }
        };
        const queryCount = (el, selector) => {
            try {
                const root = rootOf(el);
                return root.querySelectorAll(selector).length;
            } catch (e) { return 0; }
        };
        const isSecret = (el) => {
            const type = String(el && el.type || "").toLowerCase();
            const hint = `${el && el.id || ""} ${el && el.name || ""} ${attr(el, "placeholder") || ""} ${attr(el, "aria-label") || ""}`.toLowerCase();
            return type === "password" || /otp|one[-\s]?time|captcha|security\s*code|verification\s*code|auth(?:entication)?\s*code/.test(hint);
        };
        const isVisible = (el) => {
            if (!el || !el.isConnected) return false;
            const tag = el.tagName.toLowerCase();
            if (["script", "style", "noscript", "template", "meta", "link", "head", "title"].includes(tag)) return false;
            if (el.hidden) return false;
            try {
                if (el.checkVisibility) {
                    const visible = el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true });
                    if (!visible) return false;
                }
            } catch (e) {}
            let style;
            try { style = window.getComputedStyle(el); } catch (e) { return false; }
            if (!style) return false;
            if (style.display === "none" || style.visibility === "hidden" || style.visibility === "collapse" || style.opacity === "0") return false;
            try {
                if (el.closest && el.closest('[aria-hidden="true"]')) return false;
                if (el.closest && el.closest("[inert]")) return false;
            } catch (e) {}
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        };
        const tagRole = (el) => {
            const tag = el.tagName.toLowerCase();
            if (tag === "input") {
                const type = String(attr(el, "type") || "text").toLowerCase();
                if (["button", "submit", "reset", "image"].includes(type)) return "button";
                if (type === "checkbox") return "checkbox";
                if (type === "radio") return "radio";
                if (type === "range") return "slider";
                if (type === "search") return "searchbox";
                if (type === "file") return "button";
                if (type === "hidden") return "";
                return "textbox";
            }
            if (tag === "select") return el.multiple ? "listbox" : "combobox";
            if (tag === "textarea") return "textbox";
            if (tag === "a") return attr(el, "href") ? "link" : "";
            if (tag === "button") return "button";
            if (tag === "img") return "img";
            if (/^h[1-6]$/.test(tag)) return "heading";
            if (tag === "form") return "form";
            if (tag === "nav") return "navigation";
            if (tag === "main") return "main";
            if (tag === "header") return "banner";
            if (tag === "footer") return "contentinfo";
            if (tag === "table") return "table";
            if (tag === "tr") return "row";
            if (tag === "td") return "cell";
            if (tag === "th") return "columnheader";
            if (tag === "ul" || tag === "ol") return "list";
            if (tag === "li") return "listitem";
            if (tag === "dialog") return "dialog";
            if (tag === "iframe") return "iframe";
            if (el.isContentEditable) return "textbox";
            return "";
        };
        const getRole = (el) => {
            const explicit = normalize(attr(el, "role")).toLowerCase();
            return explicit || tagRole(el);
        };
        const getAccessibleName = (el) => {
            const aria = normalize(attr(el, "aria-label"));
            if (aria) return aria;
            const labelledBy = normalize(attr(el, "aria-labelledby"));
            if (labelledBy) {
                const parts = labelledBy.split(/\s+/).map((id) => document.getElementById(id)).filter(Boolean)
                    .map((node) => normalize(node.innerText || node.textContent));
                if (parts.length) return normalize(parts.join(" "));
            }
            if (el.id) {
                try {
                    const label = document.querySelector('label[for="' + cssAttr(el.id) + '"]');
                    if (label) {
                        const text = normalize(label.innerText || label.textContent);
                        if (text) return text;
                    }
                } catch (e) {}
            }
            try {
                const parentLabel = el.closest("label");
                if (parentLabel) {
                    const text = normalize(parentLabel.innerText || parentLabel.textContent);
                    if (text) return text;
                }
            } catch (e) {}
            const alt = normalize(attr(el, "alt"));
            if (alt) return alt;
            const title = normalize(attr(el, "title"));
            if (title) return title;
            const placeholder = normalize(attr(el, "placeholder"));
            if (placeholder) return placeholder;
            const tag = el.tagName.toLowerCase();
            const type = String(attr(el, "type") || "").toLowerCase();
            if (["button", "submit", "reset", "image"].includes(type) && el.value) return normalize(el.value);
            if (["button", "a", "summary", "option", "label", "legend", "caption", "figcaption", "h1", "h2", "h3", "h4", "h5", "h6"].includes(tag)) {
                const text = normalize(el.innerText || el.textContent);
                if (text) return text.slice(0, 300);
            }
            try {
                const td = el.closest("td");
                if (td && td.previousElementSibling) {
                    const text = normalize(td.previousElementSibling.innerText || td.previousElementSibling.textContent);
                    if (text) return text;
                }
            } catch (e) {}
            const name = normalize(attr(el, "name"));
            if (name && ["input", "select", "textarea", "form", "iframe"].includes(tag)) return name;
            return "";
        };
        // The human-facing question, without falling back to the placeholder
        // or the framework's field name.  Those are format hints and machine
        // identifiers; treating them as labels is what made the old scanner
        // announce date fields as "DD-MM-YYYY".
        const getLabelText = (el) => {
            let text = "";
            if (el.id) {
                try {
                    const label = document.querySelector('label[for="' + cssAttr(el.id) + '"]');
                    if (label) text += " " + (label.innerText || label.textContent || "");
                } catch (e) {}
            }
            try {
                const parentLabel = el.closest("label");
                if (parentLabel) text += " " + (parentLabel.innerText || parentLabel.textContent || "");
            } catch (e) {}
            const aria = normalize(attr(el, "aria-label"));
            if (aria) text += " " + aria;
            const labelledBy = normalize(attr(el, "aria-labelledby"));
            if (labelledBy) {
                for (const id of labelledBy.split(/\s+/)) {
                    const node = document.getElementById(id);
                    if (node) text += " " + (node.innerText || node.textContent || "");
                }
            }
            try {
                const td = el.closest("td");
                if (td && td.previousElementSibling) {
                    text += " " + (td.previousElementSibling.innerText || td.previousElementSibling.textContent || "");
                }
            } catch (e) {}
            return truncate(text, 300);
        };
        const getHelperText = (el) => {
            let text = "";
            const describedBy = normalize(attr(el, "aria-describedby"));
            if (describedBy) {
                for (const id of describedBy.split(/\s+/)) {
                    const node = document.getElementById(id);
                    if (node) text += " " + (node.innerText || node.textContent || "");
                }
            }
            return truncate(text, 500);
        };
        const ownText = (el) => {
            let text = "";
            for (const node of el.childNodes) {
                if (node.nodeType === Node.TEXT_NODE) text += " " + node.data;
            }
            return truncate(text);
        };
        const elementText = (el) => {
            const tag = el.tagName.toLowerCase();
            if (["button", "a", "label", "h1", "h2", "h3", "h4", "h5", "h6", "summary", "legend", "option"].includes(tag)) {
                return truncate(el.innerText || el.textContent || "");
            }
            if (tag === "select") {
                const selected = el.options && el.selectedIndex >= 0 ? el.options[el.selectedIndex] : null;
                return selected ? truncate(selected.text) : "";
            }
            return ownText(el);
        };
        const getOptions = (el) => {
            const tag = el.tagName.toLowerCase();
            if (tag === "select") {
                return Array.from(el.options || []).slice(0, MAX_OPTIONS).map((option, index) => ({
                    text: truncate(option.text, 300),
                    value: String(option.value || ""),
                    index: index,
                }));
            }
            const role = getRole(el);
            if (tag === "input" || !(role === "listbox" || role === "combobox" || attr(el, "aria-haspopup"))) {
                return [];
            }
            const nodes = Array.from(el.querySelectorAll('[role="option"], option')).slice(0, MAX_OPTIONS);
            return nodes.map((option, index) => ({
                text: truncate(option.innerText || option.textContent, 300),
                value: String(attr(option, "data-value") || attr(option, "value") || ""),
                index: index,
            }));
        };
        const getCss = (el) => {
            const tag = el.tagName.toLowerCase();
            if (stableId(el.id)) {
                const selector = "#" + cssEscape(el.id);
                if (queryCount(el, selector) === 1) return { css: selector, unique: true };
            }
            const name = attr(el, "name");
            if (name) {
                const selector = tag + '[name="' + cssAttr(name) + '"]';
                if (queryCount(el, selector) === 1) return { css: selector, unique: true };
            }
            for (const attribute of ["data-testid", "data-test", "data-qa", "data-cy"]) {
                const value = attr(el, attribute);
                if (value) {
                    const selector = tag + '[' + attribute + '="' + cssAttr(value) + '"]';
                    if (queryCount(el, selector) === 1) return { css: selector, unique: true };
                }
            }
            if (tag === "a") {
                const href = attr(el, "href");
                if (href) {
                    const selector = 'a[href="' + cssAttr(href) + '"]';
                    if (queryCount(el, selector) === 1) return { css: selector, unique: true };
                }
            }
            const aria = attr(el, "aria-label");
            if (aria) {
                const selector = tag + '[aria-label="' + cssAttr(aria) + '"]';
                if (queryCount(el, selector) === 1) return { css: selector, unique: true };
            }
            const placeholder = attr(el, "placeholder");
            if (placeholder) {
                const selector = tag + '[placeholder="' + cssAttr(placeholder) + '"]';
                if (queryCount(el, selector) === 1) return { css: selector, unique: true };
            }
            let classes = [];
            try { classes = Array.from(el.classList || []); } catch (e) {}
            classes = classes.filter((name) => name && !/^(active|show|open|hover|focus|selected|disabled|ng-|is-)/.test(name)).slice(0, 3);
            if (classes.length) {
                const selector = tag + classes.map((name) => "." + cssEscape(name)).join("");
                if (queryCount(el, selector) === 1) return { css: selector, unique: true };
            }
            let node = el;
            const parts = [];
            while (node && node.nodeType === 1) {
                let part = node.tagName.toLowerCase();
                const parent = node.parentElement;
                if (parent) {
                    const siblings = Array.from(parent.children).filter((child) => child.tagName === node.tagName);
                    if (siblings.length > 1) part += ":nth-of-type(" + (siblings.indexOf(node) + 1) + ")";
                }
                parts.unshift(part);
                if (node === document.documentElement) break;
                if (!parent) break;
                node = parent;
            }
            const selector = parts.join(" > ");
            return { css: selector, unique: queryCount(el, selector) === 1 };
        };
        const getXPath = (el) => {
            if (rootOf(el) instanceof ShadowRoot) return "";
            if (stableId(el.id)) {
                const xpath = "//*[@id=" + xpathString(el.id) + "]";
                try {
                    const count = document.evaluate("count(" + xpath + ")", document, null, XPathResult.NUMBER_TYPE, null).numberValue;
                    if (count === 1) return xpath;
                } catch (e) {}
            }
            let node = el;
            const parts = [];
            while (node && node.nodeType === 1) {
                let part = node.tagName.toLowerCase();
                const parent = node.parentElement;
                if (parent) {
                    const siblings = Array.from(parent.children).filter((child) => child.tagName === node.tagName);
                    if (siblings.length > 1) part += "[" + (siblings.indexOf(node) + 1) + "]";
                }
                parts.unshift(part);
                if (node === document.documentElement) break;
                node = parent;
            }
            return "/" + parts.join("/");
        };
        const getAttributes = (el) => {
            const attrs = {};
            const names = [
                "id", "name", "type", "role", "href", "src", "alt", "title", "placeholder",
                "aria-label", "aria-labelledby", "aria-describedby", "aria-expanded", "aria-haspopup",
                "aria-controls", "aria-checked", "aria-selected", "aria-disabled", "aria-required",
                "data-testid", "data-test", "data-qa", "data-cy", "contenteditable",
                "disabled", "readonly", "required", "checked", "selected", "multiple",
                "maxlength", "pattern", "autocomplete", "inputmode", "for", "tabindex"
            ];
            for (const name of names) {
                const value = attr(el, name);
                if (value !== null) attrs[name] = value;
            }
            if (el.disabled) attrs.disabled = true;
            if (el.readOnly) attrs.readonly = true;
            if (el.required) attrs.required = true;
            if (el.checked) attrs.checked = true;
            if (el.selected) attrs.selected = true;
            if ("value" in el && !isSecret(el)) attrs.has_value = String(el.value || "").length > 0;
            return attrs;
        };
        const isEditable = (el) => {
            if (el.disabled || el.readOnly) return false;
            const tag = el.tagName.toLowerCase();
            if (tag === "textarea") return true;
            if (tag === "select") return true;
            if (tag === "input") {
                const type = String(attr(el, "type") || "text").toLowerCase();
                return !["hidden", "button", "submit", "reset", "image", "checkbox", "radio", "file", "range", "color"].includes(type);
            }
            return !!el.isContentEditable;
        };
        const isInteractable = (el) => {
            if (!isVisible(el)) return false;
            const tag = el.tagName.toLowerCase();
            const role = getRole(el);
            if (el.disabled || attr(el, "aria-disabled") === "true") return false;
            let style;
            try { style = window.getComputedStyle(el); } catch (e) { style = null; }
            if (style && style.pointerEvents === "none" && !el.disabled) return false;
            if (tag === "input") {
                const type = String(attr(el, "type") || "text").toLowerCase();
                return type !== "hidden";
            }
            if (["button", "select", "textarea", "summary"].includes(tag)) return true;
            if (tag === "a") return !!attr(el, "href") || role === "button" || el.hasAttribute("onclick") || (el.tabIndex || -1) >= 0;
            if (el.isContentEditable) return true;
            if (["button", "link", "checkbox", "radio", "switch", "tab", "menuitem", "option", "combobox", "textbox", "searchbox", "slider", "spinbutton"].includes(role)) return true;
            if (el.hasAttribute("onclick") || el.hasAttribute("tabindex")) return true;
            if (style && style.cursor === "pointer") return true;
            return false;
        };
        const hashString = (value) => {
            let hash = 2166136261;
            for (let index = 0; index < value.length; index++) {
                hash ^= value.charCodeAt(index);
                hash = Math.imul(hash, 16777619);
            }
            return (hash >>> 0).toString(16).padStart(8, "0");
        };
        const elementHash = (el, role, name, text, options) => {
            const stable = [
                el.tagName.toLowerCase(),
                role,
                name,
                text,
                String(attr(el, "type") || ""),
                String(attr(el, "name") || ""),
                String(attr(el, "href") || ""),
                String(attr(el, "placeholder") || ""),
                String(attr(el, "aria-label") || ""),
                options.map((option) => option.text + "=" + option.value).join("|"),
            ].join("||");
            return hashString(stable);
        };
        const hitTest = (el) => {
            const rect = el.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) return null;
            const x = rect.left + rect.width / 2;
            const y = rect.top + rect.height / 2;
            if (x < 0 || y < 0 || x >= window.innerWidth || y >= window.innerHeight) return null;
            let hit = null;
            try { hit = document.elementFromPoint(x, y); } catch (e) { return null; }
            if (!hit) return null;
            if (hit === el || el.contains(hit) || hit.contains(el)) return null;
            try {
                const label = hit.closest && hit.closest("label");
                if (label && label.contains(el)) return null;
            } catch (e) {}
            return {
                tag: hit.tagName.toLowerCase(),
                id: hit.id || null,
                className: String(hit.className || "").slice(0, 120),
                text: truncate(hit.innerText || hit.textContent, 120),
            };
        };
        const childEntries = (el) => {
            const entries = [];
            for (const child of el.children) entries.push({ el: child, shadow: false });
            if (el.shadowRoot) {
                for (const child of el.shadowRoot.children) entries.push({ el: child, shadow: true });
            }
            return entries;
        };
        const STRUCTURAL = new Set([
            "html", "body", "main", "header", "footer", "nav", "section", "article", "aside",
            "form", "fieldset", "legend", "label", "button", "a", "input", "select", "textarea",
            "table", "thead", "tbody", "tfoot", "tr", "td", "th", "ul", "ol", "li",
            "h1", "h2", "h3", "h4", "h5", "h6", "p", "iframe", "dialog", "summary", "details",
            "figure", "figcaption"
        ]);
        const TEXTUAL = new Set(["span", "div", "small", "strong", "em", "b", "i", "font", "center"]);
        const shouldInclude = (el) => {
            const tag = el.tagName.toLowerCase();
            if (["script", "style", "noscript", "template", "meta", "link", "head", "title", "option"].includes(tag)) return false;
            if (tag === "canvas" || tag === "svg") {
                return !!(el.getAttribute("role") || /captcha|turnstile|recaptcha|h-captcha/i.test(`${el.id || ""} ${el.className || ""}`));
            }
            if (tag === "img") {
                return !!(el.getAttribute("alt") || el.getAttribute("role") || el.hasAttribute("onclick") || el.hasAttribute("tabindex"));
            }
            if (STRUCTURAL.has(tag)) return true;
            if (TEXTUAL.has(tag)) {
                if (ownText(el)) return true;
                if (el.getAttribute("role")) return true;
                if (el.hasAttribute("onclick") || el.hasAttribute("tabindex") || el.isContentEditable) return true;
                if (el.shadowRoot) return true;
                if (el.querySelector('input, select, textarea, button, a, [role], [contenteditable="true"]')) return true;
                return false;
            }
            if (el.getAttribute("role")) return true;
            if (el.shadowRoot) return true;
            if (el.hasAttribute("onclick") || el.hasAttribute("tabindex") || el.isContentEditable) return true;
            return false;
        };

        const walk = (el, parentId, depth, shadowHostId) => {
            if (!el || el.nodeType !== 1) return;
            if (elements.length >= MAX_ELEMENTS) {
                omitted += 1;
                return;
            }
            const include = shouldInclude(el);
            let currentParent = parentId;
            let currentDepth = depth;
            if (include) {
                const id = "fp-" + scanId + "-" + (++counter);
                try { el.setAttribute("data-fp-id", id); } catch (e) {}
                const tag = el.tagName.toLowerCase();
                const role = getRole(el);
                const name = getAccessibleName(el);
                const text = elementText(el);
                const options = getOptions(el);
                const css = getCss(el);
                const rect = el.getBoundingClientRect();
                const visible = isVisible(el);
                const interactable = isInteractable(el);
                const inViewport = rect.bottom > 0 && rect.right > 0 && rect.top < window.innerHeight && rect.left < window.innerWidth;
                const coveredBy = interactable && visible && inViewport ? hitTest(el) : null;
                const element = {
                    id: id,
                    frame: frameId,
                    parentId: parentId,
                    depth: depth,
                    tag: tag,
                    tagName: tag,
                    role: role,
                    name: name,
                    text: text,
                    labelText: getLabelText(el),
                    helperText: getHelperText(el),
                    attributes: getAttributes(el),
                    css: css.css,
                    cssUnique: css.unique,
                    xpath: getXPath(el),
                    rect: {
                        x: rect.x, y: rect.y, width: rect.width, height: rect.height,
                        top: rect.top, left: rect.left, right: rect.right, bottom: rect.bottom,
                    },
                    visible: visible,
                    inViewport: inViewport,
                    enabled: !el.disabled && attr(el, "aria-disabled") !== "true",
                    editable: isEditable(el),
                    interactable: interactable,
                    hoverOnly: false,
                    coveredBy: coveredBy,
                    elementHash: elementHash(el, role, name, text, options),
                    options: options,
                    children: [],
                    shadowHost: shadowHostId || null,
                };
                elements.push(element);
                byId.set(id, element);
                if (parentId && byId.has(parentId)) byId.get(parentId).children.push(id);
                else roots.push(id);
                currentParent = id;
                currentDepth = depth + 1;
            }
            for (const entry of childEntries(el)) {
                const nextShadowHost = entry.shadow
                    ? (include ? currentParent : shadowHostId)
                    : shadowHostId;
                walk(entry.el, currentParent, currentDepth, nextShadowHost);
            }
        };

        const frameworks = [];
        if (window.__reactFiber || document.querySelector("[data-reactroot]") || window._reactRootContainer) frameworks.push("React");
        if (window.ng || document.querySelector("[ng-version]") || document.querySelector("[ng-app]")) frameworks.push("Angular");
        if (window.__vue__ || window.__vue_app__ || document.querySelector("[data-v-]")) frameworks.push("Vue");
        if (window.Sys && window.Sys.WebForms) frameworks.push("ASP.NET Ajax");
        if (document.getElementById("__VIEWSTATE")) frameworks.push("ASP.NET WebForms");
        if (window.Ext) frameworks.push("ExtJS");
        if (window.jQuery) frameworks.push("jQuery");
        if (frameworks.length === 0) frameworks.push("Standard HTML5");

        walk(document.documentElement, null, 0, null);

        return {
            scanId: scanId,
            scan_id: scanId,
            url: window.location.href,
            title: document.title,
            readyState: document.readyState,
            capturedAt: scanStarted,
            captured_at: scanStarted,
            viewport: { width: window.innerWidth, height: window.innerHeight },
            scroll: { x: window.scrollX, y: window.scrollY },
            mutationCounter: window.__formpilotMutationCounter || 0,
            mutation_counter: window.__formpilotMutationCounter || 0,
            frameworks: frameworks,
            elements: elements,
            roots: roots,
            truncated: elements.length >= MAX_ELEMENTS,
            omittedCount: omitted,
            omitted_count: omitted,
            forms: Array.from(document.forms || []).map((form) => ({
                id: form.id || "",
                name: form.name || "",
                action: form.getAttribute("action") || "",
                method: form.method || "",
                elementId: form.getAttribute("data-fp-id") || null,
            })),
            dialogs: Array.from(document.querySelectorAll('dialog, [role="dialog"], [aria-modal="true"]'))
                .filter(isVisible)
                .map((dialog) => ({
                    id: dialog.id || "",
                    name: getAccessibleName(dialog),
                    text: truncate(dialog.innerText || dialog.textContent, 300),
                    elementId: dialog.getAttribute("data-fp-id") || null,
                })),
            alerts: Array.from(document.querySelectorAll('[role="alert"], .error, .alert-danger, .text-danger, .invalid-feedback, .field-validation-error'))
                .filter(isVisible)
                .map((alert) => truncate(alert.innerText || alert.textContent, 300))
                .filter(Boolean),
        };
    }
    """

    @classmethod
    async def scan(cls, page) -> Tuple[Dict[str, Any], "PageBlueprint"]:
        """Scan every frame and return (legacy DOM, typed blueprint).

        ``STRUCTURE_JS`` stamps elements and builds the tree.  ``DETECTION_JS``
        then runs against the same DOM so the existing form model keeps
        working.  The two passes are synchronous with respect to page state:
        no navigation happens between them.
        """
        from .blueprint import PageBlueprint

        if page is None:
            raise ValueError("A live page is required for a DOM scan.")

        frames = list(page.frames or [])
        main_frame = page.main_frame
        all_elements: list[Dict[str, Any]] = []
        frame_infos: list[Dict[str, Any]] = []
        merged: Dict[str, Any] = {
            "title": "",
            "url": getattr(page, "url", "") or "",
            "frameworks": [],
            "gateways": [],
            "applicationLinks": [],
            "inputs": [],
            "nextButtons": [],
            "captchaElements": [],
            "errors": [],
            "visibleText": "",
            "loading": False,
            "paymentSignals": 0,
            "hasPaymentButton": False,
            "activeSectionId": "",
            "stepHeading": "",
            "formCount": 0,
            "formAction": "",
            "fileInputs": [],
            "livePhotoRequired": False,
            "otpInputs": [],
            "elements": [],
            "roots": [],
            "forms": [],
            "dialogs": [],
            "alerts": [],
        }
        main_structure: Optional[Dict[str, Any]] = None

        for index, frame in enumerate(frames):
            frame_id = "main" if frame == main_frame else f"frame-{index}"
            frame_info: Dict[str, Any] = {
                "id": frame_id,
                "index": index,
                "url": getattr(frame, "url", "") or "",
                "name": getattr(frame, "name", "") or "",
                "accessible": True,
            }
            try:
                structure = await frame.evaluate(cls.STRUCTURE_JS, frame_id)
            except Exception as exc:
                frame_info["accessible"] = False
                frame_info["error"] = str(exc)[:200]
                frame_infos.append(frame_info)
                continue

            try:
                legacy = await frame.evaluate(cls.DETECTION_JS)
            except Exception as exc:
                # The structure pass is still useful: a frame can expose its
                # controls even when the legacy classifier trips on a widget.
                legacy = {}
                frame_info["legacy_error"] = str(exc)[:200]

            frame_infos.append(frame_info)
            if frame == main_frame:
                main_structure = structure
                merged["title"] = str(structure.get("title") or "")
                merged["url"] = str(structure.get("url") or merged["url"])
                merged["frameworks"] = list(structure.get("frameworks") or [])
                merged["forms"] = list(structure.get("forms") or [])
                merged["dialogs"] = list(structure.get("dialogs") or [])
                merged["alerts"] = list(structure.get("alerts") or [])
                for key in (
                    "visibleText",
                    "loading",
                    "paymentSignals",
                    "hasPaymentButton",
                    "activeSectionId",
                    "stepHeading",
                    "formCount",
                    "formAction",
                    "livePhotoRequired",
                ):
                    if key in legacy:
                        merged[key] = legacy[key]

            for element in structure.get("elements") or []:
                if not isinstance(element, dict):
                    continue
                element["frame"] = frame_id
                element["frame_index"] = index
                all_elements.append(element)

            for key in ("inputs", "gateways", "applicationLinks", "nextButtons", "captchaElements", "fileInputs", "otpInputs"):
                for item in legacy.get(key) or []:
                    if isinstance(item, dict):
                        item["frame"] = frame_id
                        item["frame_index"] = index
                        merged[key].append(item)

            for error in legacy.get("errors") or []:
                text = str(error or "").strip()
                if text and text not in merged["errors"]:
                    merged["errors"].append(text)
            for framework in legacy.get("frameworks") or []:
                if framework and framework not in merged["frameworks"]:
                    merged["frameworks"].append(framework)

        if main_structure is None:
            raise RuntimeError("The main frame could not be scanned.")

        scan_id = str(main_structure.get("scanId") or main_structure.get("scan_id") or "")
        merged["scan_id"] = scan_id
        merged["captured_at"] = str(main_structure.get("capturedAt") or "")
        merged["ready_state"] = str(main_structure.get("readyState") or "")
        merged["viewport"] = main_structure.get("viewport") or {}
        merged["scroll"] = main_structure.get("scroll") or {}
        merged["mutation_counter"] = main_structure.get("mutationCounter") or 0
        merged["truncated"] = bool(main_structure.get("truncated"))
        merged["omitted_count"] = int(main_structure.get("omittedCount") or 0)
        merged["elements"] = all_elements
        merged["roots"] = list(main_structure.get("roots") or [])
        merged["frames"] = frame_infos

        blueprint = PageBlueprint.from_scan(
            {
                "scan_id": scan_id,
                "url": merged["url"],
                "title": merged["title"],
                "elements": all_elements,
                "roots": merged["roots"],
                "captured_at": merged["captured_at"],
                "truncated": merged["truncated"],
                "omitted_count": merged["omitted_count"],
                "ready_state": merged["ready_state"],
                "viewport": merged["viewport"],
                "scroll": merged["scroll"],
                "mutation_counter": merged["mutation_counter"],
                "frameworks": merged["frameworks"],
            },
            frames=frame_infos,
        )
        blueprint.enrich_legacy(merged)
        return merged, blueprint
