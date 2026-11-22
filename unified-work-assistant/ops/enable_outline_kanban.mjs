import fs from 'node:fs';
const file='.local/compose.json',config=JSON.parse(fs.readFileSync(file));
const tag=process.argv[2]||'kanban-20261002';
fs.mkdirSync('backups/pre-outline-kanban-20261002',{recursive:true});
const backup='backups/pre-outline-kanban-20261002/compose.private.json';
if(!fs.existsSync(backup))fs.copyFileSync(file,backup);
for(const service of ['outline','workhub']){
 config.services[service].environment.OUTLINE_KANBAN_ENABLED='true';
 config.services[service].image=`unified-work-assistant/${service}:${tag}`;
}
fs.writeFileSync(file,JSON.stringify(config,null,2)+'\n');
console.log('Configured Kanban; private rollback settings saved.');
