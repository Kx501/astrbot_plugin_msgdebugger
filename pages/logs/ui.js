/* Shared DOM components. All observed content is rendered as text. */
export function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}
export function card(title, parent) {
  const node = el('article', null, 'card');
  node.append(el('h3', title));
  parent.append(node);
  return node;
}
export function raw(title, value, parent, open = false) {
  const details = el('details');
  details.open = open;
  details.append(el('summary', title), el('pre', typeof value === 'string' ? value : JSON.stringify(value, null, 2)));
  parent.append(details);
  return details;
}
export function button(label, action, parent) {
  const node = el('button', label);
  node.type = 'button';
  node.onclick = async () => {
    node.disabled = true;
    try { await action(); }
    catch (error) { document.querySelector('#notice').textContent = error.message; }
    finally { node.disabled = false; }
  };
  parent.append(node);
  return node;
}
export function select(label, options, value, action, parent) {
  const wrapper = el('label', label + ' ');
  const node = el('select');
  for (const [key, title] of options) {
    const option = el('option', title);
    option.value = key;
    node.append(option);
  }
  node.value = value;
  node.onchange = () => Promise.resolve(action(node.value)).catch(error => { document.querySelector('#notice').textContent = error.message; });
  wrapper.append(node);
  parent.append(wrapper);
  return node;
}
export function hint(text, parent) { parent.append(el('p', text, 'hint')); }
export const dataOf = stage => stage?.fields?.find(field => field.key === 'detail')?.json || {};
