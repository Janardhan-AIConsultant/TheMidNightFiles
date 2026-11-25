// Loads the REAL versioned prompt (prompts/<agent>/<version>.md) so promptfoo tests exactly what ships.
const fs = require('fs');
const path = require('path');

function load(agent, version = 'v1') {
  return fs.readFileSync(path.join(__dirname, '..', '..', 'prompts', agent, `${version}.md`), 'utf8');
}

module.exports.writer = async ({ vars }) => [
  { role: 'system', content: load('writer') },
  { role: 'user', content: JSON.stringify({ brief: vars.brief, profile: { min_words: 120, target_words: 200 } }) },
];

module.exports.safety = async ({ vars }) => [
  { role: 'system', content: load('safety') },
  { role: 'user', content: JSON.stringify({ story_text: vars.story_text, section: 0, total_sections: 1 }) },
];
