import fs from 'node:fs';

const file='.local/compose.json';
const config=JSON.parse(fs.readFileSync(file));
const directory='backups/pre-outline-kanban-polish-20261002';
fs.mkdirSync(directory,{recursive:true});
const backup=directory+'/compose.private.json';
if(!fs.existsSync(backup))fs.copyFileSync(file,backup);
config.services.outline.image='unified-work-assistant/outline:kanban-polish-20261002';
fs.writeFileSync(file,JSON.stringify(config,null,2)+'\n');
console.log('Configured Kanban polish; private rollback settings saved.');
