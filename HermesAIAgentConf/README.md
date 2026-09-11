1) Add this at the end of .hermes/hermes-agent/AGENTS.md

# AGENTS.md
Always inspect `CMDB.md` at the root of the repository to understand the technologies, environment constraints, and path conventions before proposing architectural changes or writing code.


2) Create Profile

hermes profile create your-new-profile

3) Config the new profile

your-new-profile setup 

    - SLM/LLM of your choice
    - Tools: allow terminal execution to execute the python script
    - Skills: 
            - Config custom skill see SKILL.md in this folder
            - You can also check other skills https://hermes-agent.nousresearch.com/docs/skills