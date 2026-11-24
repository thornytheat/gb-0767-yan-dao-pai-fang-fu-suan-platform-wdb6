const form = document.querySelector('#monitor-form');
const sample = document.querySelector('#sample');
const feedback = document.querySelector('#feedback');
const locationFor = (name, run) => {
  const url = new URL(location.href);
  url.searchParams.set('sample', name);
  if (run) url.searchParams.set('run', run);
  else url.searchParams.delete('run');
  return url;
};
sample.addEventListener('change', () => location.assign(locationFor(sample.value)));
form.addEventListener('submit', async event => {
  event.preventDefault();
  const button = form.querySelector('button');
  button.disabled = true;
  feedback.hidden = false;
  feedback.dataset.failed = 'false';
  feedback.textContent = '正在复算与归档';
  try {
    const response = await fetch('/api/runs', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({sample: sample.value}),
    });
    const record = await response.json();
    if (!response.ok) throw new Error(record.detail);
    const target = locationFor(sample.value, record.run_id);
    if (target.href === location.href) feedback.textContent = '已复用原归档';
    else location.assign(target);
  } catch (error) {
    feedback.dataset.failed = 'true';
    feedback.textContent = error.message || '归档失败，请重试';
  } finally {
    button.disabled = false;
  }
});
const filter = document.querySelector('#state-filter');
filter?.addEventListener('change', () => {
  for (const row of document.querySelectorAll('#verdict-table tbody tr')) {
    row.hidden = filter.value !== 'all' && (filter.value === 'late' ? row.dataset.late !== 'True' : row.dataset.state !== filter.value);
  }
});

const clockForm = document.querySelector('.clock-confirm');
clockForm?.addEventListener('submit', async event => {
  event.preventDefault();
  const button = clockForm.querySelector('button');
  const feedback = clockForm.querySelector('.clock-feedback');
  const runId = clockForm.dataset.run;
  button.disabled = true;
  feedback.hidden = false;
  feedback.dataset.failed = 'false';
  feedback.textContent = '正在接受校时确认并重算';
  try {
    const response = await fetch(`/api/runs/${runId}/clock-confirmation`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ticket: clockForm.elements.ticket.value}),
    });
    const record = await response.json();
    if (!response.ok) throw new Error(record.detail);
    feedback.textContent = record.reused ? '该凭据已确认，已复用重算结果' : '校时已确认，正在刷新对账';
    setTimeout(() => location.reload(), 600);
  } catch (error) {
    feedback.dataset.failed = 'true';
    feedback.textContent = error.message || '校时确认失败，请重试';
    button.disabled = false;
  }
});
