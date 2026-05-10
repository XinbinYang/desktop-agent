import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import zh from './locales/zh.json';
import en from './locales/en.json';

function getInitialLocale(): string {
  try {
    const stored = localStorage.getItem('desktop-agent-locale');
    if (stored === 'zh' || stored === 'en') return stored;
  } catch { /* ignore */ }
  return 'zh';
}

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: { zh: { translation: zh }, en: { translation: en } },
    lng: getInitialLocale(),
    fallbackLng: 'zh',
    interpolation: { escapeValue: false },
    detection: { order: [], caches: [] },
  });

export default i18n;
