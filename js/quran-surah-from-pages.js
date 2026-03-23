/**
 * Word-by-word surah text from the same JSON as index.html (data/pages/*.json).
 * Verse assembly mirrors index.html parsePageJson(): iterate v.words in order,
 * include only char_type_name === 'word', use text_uthmani || text (no trimming).
 *
 * Optional: point pagesBase at data/indopak13/pages/ if you add IndoPak mode later.
 */
(function (global) {
  'use strict';

  var VERSES_PER_SURAH = [7,286,200,176,120,165,206,75,129,109,123,111,43,52,99,128,111,110,98,135,112,78,118,64,77,227,93,88,69,60,34,30,73,54,45,83,182,88,75,85,54,53,89,59,37,35,38,29,18,45,60,49,62,55,78,96,29,22,24,13,14,11,11,18,12,12,30,52,52,44,28,28,20,56,40,31,50,40,46,42,29,19,36,25,22,17,19,26,30,20,15,21,11,8,8,19,5,8,8,11,11,8,3,9,5,4,7,3,6,3,5,4,5,6];

  var _surahToPages = null;

  function isBismillahAyah(text) {
    if (!text || text.length > 220) return false;
    var t = String(text).trim().replace(/[\u064B-\u065F\u0670\u0610-\u061A]/g, '').replace(/\u0671/g, 'ا').replace(/ٱ/g, 'ا').replace(/\s+/g, '');
    return t.length >= 8 && t.indexOf('بسم') === 0;
  }

  /** Same word pick as index.html parsePageJson (playlist text). */
  function verseWordStrings(v) {
    var out = [];
    var wlist = v.words || [];
    for (var i = 0; i < wlist.length; i++) {
      var w = wlist[i];
      if (w.char_type_name === 'word') {
        var t = w.text_uthmani != null ? w.text_uthmani : w.text;
        if (t == null) t = '';
        out.push(String(t));
      }
    }
    return out;
  }

  function mergePageVersesStructured(json, surahNum, into) {
    var verses = json.verses || [];
    for (var vi = 0; vi < verses.length; vi++) {
      var v = verses[vi];
      var vk = v.verse_key;
      if (!vk) continue;
      if (parseInt(String(vk).split(':')[0], 10) !== surahNum) continue;
      into.set(vk, { words: verseWordStrings(v) });
    }
  }

  function ensureSurahToPages(fullQuranUrl) {
    fullQuranUrl = fullQuranUrl || 'data/full_quran.json';
    if (_surahToPages) return Promise.resolve();
    return fetch(fullQuranUrl).then(function (r) {
      if (!r.ok) throw new Error('full_quran.json');
      return r.json();
    }).then(function (data) {
      _surahToPages = {};
      Object.keys(data).forEach(function (pg) {
        var val = data[pg];
        (val.surahs || []).forEach(function (s) {
          if (!_surahToPages[s]) _surahToPages[s] = [];
          _surahToPages[s].push(Number(pg));
        });
      });
      Object.keys(_surahToPages).forEach(function (k) {
        _surahToPages[k].sort(function (a, b) { return a - b; });
      });
    });
  }

  /**
   * @param {number} surahNum 1..114
   * @param {{ pagesBase?: string, fullQuranUrl?: string }} opt
   * @returns {Promise<{ textRaw: string, words: string[], ayahWords: { vk: string, text: string, words: string[] }[] }>}
   */
  function loadSurahStructured(surahNum, opt) {
    opt = opt || {};
    var pagesBase = opt.pagesBase || 'data/pages/';
    var fullQuranUrl = opt.fullQuranUrl || 'data/full_quran.json';
    return ensureSurahToPages(fullQuranUrl).then(function () {
      var need = VERSES_PER_SURAH[surahNum - 1];
      var pages = _surahToPages[surahNum] || [];
      var combined = new Map();
      var p = Promise.resolve();
      for (var i = 0; i < pages.length; i++) {
        (function (pg) {
          p = p.then(function () {
            if (combined.size >= need) return;
            return fetch(pagesBase + pg + '.json').then(function (res) {
              if (!res.ok) throw new Error('page ' + pg);
              return res.json();
            }).then(function (j) {
              mergePageVersesStructured(j, surahNum, combined);
            });
          });
        })(pages[i]);
      }
      return p.then(function () {
        if (combined.size < need) throw new Error('incomplete surah data');
        var keys = Array.from(combined.keys()).sort(function (a, b) {
          return parseInt(String(a).split(':')[1], 10) - parseInt(String(b).split(':')[1], 10);
        });
        var ayahWords = keys.map(function (k) {
          var entry = combined.get(k);
          var arr = (entry && entry.words) ? entry.words.slice() : [];
          return { vk: k, words: arr, text: arr.join(' ') };
        });
        if (surahNum !== 9 && surahNum !== 1 && ayahWords.length && isBismillahAyah(ayahWords[0].text)) {
          ayahWords.shift();
        }
        var flatWords = [];
        for (var ai = 0; ai < ayahWords.length; ai++) {
          var aw = ayahWords[ai].words;
          for (var wi = 0; wi < aw.length; wi++) flatWords.push(aw[wi]);
        }
        var textRaw = ayahWords.map(function (a) { return a.text; }).join(' ');
        return { textRaw: textRaw, words: flatWords, ayahWords: ayahWords };
      });
    });
  }

  global.QuranSurahFromPages = {
    VERSES_PER_SURAH: VERSES_PER_SURAH,
    loadSurahStructured: loadSurahStructured,
    ensureSurahToPages: ensureSurahToPages,
    /** Test hook or hot reload */
    resetPageIndexCache: function () { _surahToPages = null; },
    verseWordStrings: verseWordStrings
  };
})(typeof window !== 'undefined' ? window : globalThis);
