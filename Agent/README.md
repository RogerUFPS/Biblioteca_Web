Launch the dockerfile with the next command:

`docker run -d -p 11434:11434 --name ollama-custom ollama-custom`

How to ask something to a model:

`docker exec -it <container_name> ollama run <modelo> "Message"`

Stop a model when you want to change it:

`docker exec -it <container_name> ollama stop <model>`

Idea of the proccess:

1. Check knowledges areas and academic programs via API.
2. Detect language and keywords that are related to those knowledge areas and academic programs.
3. Check public platforms and journals that has those knowledge areas and academic programs via API.
4. Check the ValidSintaxis of the platform via API.
5. Generate 3 search strings with the titles of the journals, knowledge areas and academic program based on the top platforms that has most quantity of information related.
