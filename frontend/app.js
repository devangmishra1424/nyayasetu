function formatAnswer(text) {
  if (!text) return "";

  // Split into lines and process each
  const lines = text.split('\n');
  let html = '';
  let inTable = false;
  let tableHtml = '';
  let inList = false;
  let listType = '';

  for (let i = 0; i < lines.length; i++) {
    let line = lines[i];

    // Table row
    if (line.trim().startsWith('|')) {
      if (line.match(/^\|[\s\-|]+\|$/)) continue; // skip separator rows
      if (!inTable) { tableHtml = '<table class="answer-table">'; inTable = true; }
      const cells = line.split('|').filter((c, i, a) => i > 0 && i < a.length - 1);
      const isHeader = i === 0 || !lines[i-1]?.trim().startsWith('|');
      const tag = isHeader ? 'th' : 'td';
      tableHtml += '<tr>' + cells.map(c => `<${tag}>${inline(c.trim())}</${tag}>`).join('') + '</tr>';
      continue;
    } else if (inTable) {
      html += tableHtml + '</table>';
      tableHtml = '';
      inTable = false;
    }

    // Numbered list
    if (line.match(/^\d+\.\s+/)) {
      if (!inList || listType !== 'ol') {
        if (inList) html += `</${listType}>`;
        html += '<ol>'; inList = true; listType = 'ol';
      }
      html += `<li>${inline(line.replace(/^\d+\.\s+/, ''))}</li>`;
      continue;
    }

    // Bullet list (* or -)
    if (line.match(/^[\*\-]\s+/)) {
      if (!inList || listType !== 'ul') {
        if (inList) html += `</${listType}>`;
        html += '<ul>'; inList = true; listType = 'ul';
      }
      html += `<li>${inline(line.replace(/^[\*\-]\s+/, ''))}</li>`;
      continue;
    }

    // Close list if needed
    if (inList && line.trim() === '') {
      html += `</${listType}>`;
      inList = false; listType = '';
    }

    // Headers
    if (line.startsWith('### ')) { html += `<h3>${inline(line.slice(4))}</h3>`; continue; }
    if (line.startsWith('## '))  { html += `<h2>${inline(line.slice(3))}</h2>`; continue; }
    if (line.startsWith('# '))   { html += `<h1>${inline(line.slice(2))}</h1>`; continue; }

    // Empty line = paragraph break
    if (line.trim() === '') { html += '<br>'; continue; }

    // Normal line
    html += `<p>${inline(line)}</p>`;
  }

  // Close any open tags
  if (inTable) html += tableHtml + '</table>';
  if (inList) html += `</${listType}>`;

  return html;
}

function inline(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>');
}