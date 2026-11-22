import fs from 'node:fs';
const file='.local/compose.json',config=JSON.parse(fs.readFileSync(file));
const directory='backups/pre-outline-kanban-first-drop-20261006';
fs.mkdirSync(directory,{recursive:true});
if(!fs.existsSync(directory+'/compose.private.json'))fs.copyFileSync(file,directory+'/compose.private.json');
config.services.outline.image='unified-work-assistant/outline:kanban-first-drop-20261006';
fs.writeFileSync(file,JSON.stringify(config,null,2)+'\n');
console.log('Configured first-event drop acceptance and refresh-safe gestures; rollback settings saved.');
