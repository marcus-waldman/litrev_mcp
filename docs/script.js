// litrev-mcp Reference Guide - Interactive Features

// ============================================================================
// Dark Mode Toggle
// ============================================================================

function initTheme() {
    // Check for saved preference or default to system preference
    const savedTheme = localStorage.getItem('theme');
    const systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;

    const theme = savedTheme || (systemPrefersDark ? 'dark' : 'light');
    setTheme(theme);

    // Update button text
    updateThemeButton(theme);
}

function setTheme(theme) {
    if (theme === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
    } else {
        document.documentElement.removeAttribute('data-theme');
    }
    localStorage.setItem('theme', theme);
}

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    setTheme(newTheme);
    updateThemeButton(newTheme);
}

function updateThemeButton(theme) {
    const button = document.getElementById('theme-toggle');
    button.textContent = theme === 'dark' ? '☀️' : '🌙';
    button.setAttribute('aria-label', theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
}

// ============================================================================
// Copy to Clipboard
// ============================================================================

function setupCopyButtons() {
    const copyButtons = document.querySelectorAll('.copy-btn');

    copyButtons.forEach(button => {
        button.addEventListener('click', async function() {
            const text = this.getAttribute('data-text');

            try {
                await navigator.clipboard.writeText(text);

                // Visual feedback
                const originalText = this.textContent;
                this.textContent = '✓ Copied!';
                this.classList.add('copied');

                setTimeout(() => {
                    this.textContent = originalText;
                    this.classList.remove('copied');
                }, 2000);

            } catch (err) {
                console.error('Failed to copy:', err);

                // Fallback for older browsers
                const textarea = document.createElement('textarea');
                textarea.value = text;
                textarea.style.position = 'fixed';
                textarea.style.opacity = '0';
                document.body.appendChild(textarea);
                textarea.select();

                try {
                    document.execCommand('copy');
                    this.textContent = '✓ Copied!';
                    this.classList.add('copied');

                    setTimeout(() => {
                        this.textContent = 'Copy';
                        this.classList.remove('copied');
                    }, 2000);
                } catch (err2) {
                    console.error('Fallback copy failed:', err2);
                    this.textContent = '✗ Failed';
                    setTimeout(() => {
                        this.textContent = 'Copy';
                    }, 2000);
                } finally {
                    document.body.removeChild(textarea);
                }
            }
        });
    });
}

// ============================================================================
// Search Functionality
// ============================================================================

function setupSearch() {
    const searchInput = document.getElementById('search');
    const sections = document.querySelectorAll('main section');
    const tables = document.querySelectorAll('table');
    const promptBoxes = document.querySelectorAll('.prompt-box');
    const details = document.querySelectorAll('details');

    searchInput.addEventListener('input', function() {
        const query = this.value.toLowerCase().trim();

        if (query === '') {
            // Show everything
            sections.forEach(section => section.classList.remove('hidden'));
            tables.forEach(table => {
                const rows = table.querySelectorAll('tbody tr');
                rows.forEach(row => row.classList.remove('hidden'));
            });
            promptBoxes.forEach(box => box.classList.remove('hidden'));
            details.forEach(detail => detail.classList.remove('hidden'));
            return;
        }

        // Search in sections
        sections.forEach(section => {
            const text = section.textContent.toLowerCase();
            if (text.includes(query)) {
                section.classList.remove('hidden');
            } else {
                section.classList.add('hidden');
            }
        });

        // Search in table rows
        tables.forEach(table => {
            const rows = table.querySelectorAll('tbody tr');
            let hasVisibleRow = false;

            rows.forEach(row => {
                const text = row.textContent.toLowerCase();
                if (text.includes(query)) {
                    row.classList.remove('hidden');
                    hasVisibleRow = true;
                } else {
                    row.classList.add('hidden');
                }
            });

            // Hide table header if no rows match
            const thead = table.querySelector('thead');
            if (hasVisibleRow) {
                thead.classList.remove('hidden');
            } else {
                thead.classList.add('hidden');
            }
        });

        // Search in prompt boxes
        promptBoxes.forEach(box => {
            const text = box.textContent.toLowerCase();
            if (text.includes(query)) {
                box.classList.remove('hidden');
            } else {
                box.classList.add('hidden');
            }
        });

        // Search in collapsible details
        details.forEach(detail => {
            const text = detail.textContent.toLowerCase();
            if (text.includes(query)) {
                detail.classList.remove('hidden');
                detail.setAttribute('open', ''); // Open matching details
            } else {
                detail.classList.add('hidden');
            }
        });
    });

    // Clear search on Escape
    searchInput.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            this.value = '';
            this.dispatchEvent(new Event('input'));
            this.blur();
        }
    });
}

// ============================================================================
// Smooth Scroll for TOC Links
// ============================================================================

function setupSmoothScroll() {
    const tocLinks = document.querySelectorAll('.toc a');

    tocLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            const targetId = this.getAttribute('href');
            const targetElement = document.querySelector(targetId);

            if (targetElement) {
                targetElement.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });

                // Update URL without jumping
                history.pushState(null, null, targetId);
            }
        });
    });
}

// ============================================================================
// Highlight Current Section in TOC
// ============================================================================

function setupScrollSpy() {
    const sections = document.querySelectorAll('main section');
    const tocLinks = document.querySelectorAll('.toc a');

    function highlightTOC() {
        let current = '';

        sections.forEach(section => {
            const sectionTop = section.offsetTop;
            const sectionHeight = section.clientHeight;

            if (window.pageYOffset >= sectionTop - 100) {
                current = section.getAttribute('id');
            }
        });

        tocLinks.forEach(link => {
            link.classList.remove('active');
            if (link.getAttribute('href') === `#${current}`) {
                link.classList.add('active');
            }
        });
    }

    window.addEventListener('scroll', highlightTOC);
    highlightTOC(); // Initial call
}

// ============================================================================
// Initialize Everything
// ============================================================================

document.addEventListener('DOMContentLoaded', function() {
    // Initialize theme
    initTheme();

    // Setup theme toggle button
    const themeToggle = document.getElementById('theme-toggle');
    themeToggle.addEventListener('click', toggleTheme);

    // Setup copy buttons
    setupCopyButtons();

    // Setup search
    setupSearch();

    // Setup smooth scrolling
    setupSmoothScroll();

    // Setup scroll spy for TOC
    setupScrollSpy();

    // Focus search on '/' key
    document.addEventListener('keydown', function(e) {
        if (e.key === '/' && e.target.tagName !== 'INPUT') {
            e.preventDefault();
            document.getElementById('search').focus();
        }
    });

    console.log('litrev-mcp Reference Guide loaded successfully!');
});

// Listen for system theme changes
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', e => {
    if (!localStorage.getItem('theme')) {
        const newTheme = e.matches ? 'dark' : 'light';
        setTheme(newTheme);
        updateThemeButton(newTheme);
    }
});
