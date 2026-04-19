const button = document.getElementById('actionBtn');
const heading = document.getElementById('greeting');

button.addEventListener('click', function() {
    heading.innerText = "You clicked the button! 🎉";
    heading.style.color = "#28a745";
    
    // Adding the random background color logic just because
    const randomColor = '#' + Math.floor(Math.random()*16777215).toString(16);
    document.body.style.backgroundColor = randomColor;
});