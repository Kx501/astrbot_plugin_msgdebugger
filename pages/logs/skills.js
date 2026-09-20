/* Read directory evidence from request snapshots, never from name mentions. */
export function requestSkills(messages = []) {
  const entries = [];
  for (const [index, message] of messages.entries()) {
    if (!['system', 'developer'].includes(message?.role)) continue;
    const text = typeof message.content === 'string' ? message.content :
      (Array.isArray(message.content) ? message.content.filter(p => typeof p?.text === 'string').map(p => p.text).join('\n') : '');
    for (const section of text.matchAll(/^### Available skills\s*\r?\n([\s\S]*?)(?=^#{1,3} |$(?![\s\S]))/gm)) {
      for (const match of section[1].matchAll(/^- \*\*(.+?)\*\*: ([\s\S]*?)\r?\n[ \t]+File: `([^`\r\n]+)`/gm)) {
        entries.push({name: match[1], description: match[2].trim(), path: match[3], messageIndex: index});
      }
    }
  }
  return entries;
}
