import fs from 'node:fs';
const file='.local/compose.json',config=JSON.parse(fs.readFileSync(file));
const directory='backups/pre-outline-kanban-reset-20261006';
fs.mkdirSync(directory,{recursive:true});
if(!fs.existsSync(directory+'/compose.private.json'))fs.copyFileSync(file,directory+'/compose.private.json');
for(const service of ['outline','workhub'])config.services[service].image=`unified-work-assistant/${service}:kanban-reset-20261006`;
fs.writeFileSync(file,JSON.stringify(config,null,2)+'\n');
console.log('Configured whole-card grab, checklist reset and persistent workflow mode; rollback settings saved.');
