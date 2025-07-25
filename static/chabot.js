document.addEventListener('DOMContentLoaded', () => {
    const chatWindow = document.getElementById('chat-window');
    const chatForm = document.getElementById('chat-form');
    const userInput = document.getElementById('user-input');
    const typingIndicator = document.getElementById('typing-indicator');
    const micButton = document.getElementById('mic-button');

    function appendMessage(sender, message) {
        const messageWrapper = document.createElement('div');
        const messageBubble = document.createElement('div');

        messageBubble.textContent = message;
        messageBubble.classList.add(
            'rounded-xl', 'px-5', 'py-3', 'max-w-lg', 'text-base', 'leading-relaxed', 'shadow-sm', 'break-words', 'fade-in'
        );

        if (sender === 'user') {
            messageWrapper.classList.add('flex', 'justify-end', 'py-8');
            messageBubble.classList.add('bg-[#2f5930]', 'text-white', 'shadow-md');
        } else {
            messageWrapper.classList.add('flex', 'justify-start');
            messageBubble.classList.add('bg-white', 'text-[#2d2d2d]', 'border', 'border-gray-300');
        }

        messageWrapper.appendChild(messageBubble);
        chatWindow.appendChild(messageWrapper);
        chatWindow.scrollTop = chatWindow.scrollHeight;
    }

    function showTyping(show = true) {
        typingIndicator.classList.toggle('hidden', !show);
    }

    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        const message = userInput.value.trim();
        if (!message) return;

        appendMessage('user', message);
        userInput.value = '';
        userInput.disabled = true;
        showTyping(true);

        try {
            const response = await fetch('/message', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message })
            });

            const data = await response.json();
            if (response.ok) {
                appendMessage('bot', data.reply);
            } else {
                appendMessage('bot', 'Sorry, there was an error. Please try again.');
            }
        } catch (error) {
            appendMessage('bot', 'Network error. Please try again.');
        } finally {
            userInput.disabled = false;
            userInput.focus();
            showTyping(false);
        }
    });

    if (micButton && 'webkitSpeechRecognition' in window) {
        const recognition = new webkitSpeechRecognition();
        recognition.continuous = false;
        recognition.lang = 'en-US';
        recognition.interimResults = false;

        micButton.addEventListener('click', () => {
            recognition.start();
            micButton.classList.add('text-[#2f5930]');
        });

        recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            userInput.value = transcript;
        };

        recognition.onend = () => {
            micButton.classList.remove('text-[#2f5930]');
        };
    } else if (micButton) {
        micButton.disabled = true;
        micButton.title = 'Voice input not supported on this browser.';
    }
});
