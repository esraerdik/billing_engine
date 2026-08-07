const tableBody = document.querySelector("#apartmentTable tbody");
const addButton = document.getElementById("addApartment");

addButton.addEventListener("click", () => {

    const rowCount = tableBody.rows.length + 1;

    const row = document.createElement("tr");

    row.innerHTML = `
        <td>${rowCount}</td>

        <td><input type="number"></td>

        <td><input type="number"></td>

        <td>
            <button class="delete-btn">Sil</button>
        </td>
    `;

    tableBody.appendChild(row);

});

tableBody.addEventListener("click", function (e){

    if(e.target.classList.contains("delete-btn")){

        e.target.closest("tr").remove();

        [...tableBody.rows].forEach((row,index)=>{

            row.cells[0].textContent=index+1;

        });

    }

});